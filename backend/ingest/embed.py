"""Vector embedding ingestion pipeline step.

Per ARCHITECTURE.md sections 5, 6.1, 7, 19:
- Embed text per label:
    Doc = display + newline + body
    Decision = display + newline + summary + newline + rationale
    Thread = text
  Explicitly skips: Person, Team, Module, File, PR, Ticket, ReviewRequest.
- Computes text_hash = sha256(exact_embed_text).
- Skips nodes whose stored text_hash equals the new hash and already have an embedding.
- Calls embed_documents() using GEMINI_EMBED_MODEL, EMBED_DIM, and task_type='RETRIEVAL_DOCUMENT'.
- Batches API requests with exponential backoff on 429/5xx.
- Stores vector into FalkorDB with SET n.embedding = vecf32(item.vec), n.text_hash = item.text_hash.
- Prints counts: embedded, skipped, per label and total.
"""

import hashlib
import sys
from typing import Any, Dict, List, Optional, Tuple

from brain_core.config import Settings, get_settings
from brain_core.db import get_graph
from brain_core.embeddings import embed_documents
from ingest.loaders import BATCH_SIZE, _execute_batch


def _collect_doc_items(graph: Any) -> Tuple[List[Dict[str, Any]], int]:
    """Collect Doc nodes needing embedding vs skipped."""
    res = graph.query("MATCH (d:Doc) RETURN d.id, d.display, d.body, d.text_hash, d.embedding IS NOT NULL")
    items_to_embed = []
    skipped = 0

    for row in res.result_set:
        d_id = row[0]
        display = row[1] or ""
        body = row[2] or ""
        stored_hash = row[3] or ""
        has_embedding = bool(row[4])

        embed_text = f"{display}\n{body}"
        new_hash = hashlib.sha256(embed_text.encode("utf-8")).hexdigest()

        if has_embedding and stored_hash == new_hash:
            skipped += 1
        else:
            items_to_embed.append({
                "id": d_id,
                "text": embed_text,
                "text_hash": new_hash,
            })

    return items_to_embed, skipped


def _collect_decision_items(graph: Any) -> Tuple[List[Dict[str, Any]], int]:
    """Collect Decision nodes needing embedding vs skipped."""
    res = graph.query("MATCH (d:Decision) RETURN d.id, d.display, d.summary, d.rationale, d.text_hash, d.embedding IS NOT NULL")
    items_to_embed = []
    skipped = 0

    for row in res.result_set:
        d_id = row[0]
        display = row[1] or ""
        summary = row[2] or ""
        rationale = row[3] or ""
        stored_hash = row[4] or ""
        has_embedding = bool(row[5])

        embed_text = f"{display}\n{summary}\n{rationale}"
        new_hash = hashlib.sha256(embed_text.encode("utf-8")).hexdigest()

        if has_embedding and stored_hash == new_hash:
            skipped += 1
        else:
            items_to_embed.append({
                "id": d_id,
                "text": embed_text,
                "text_hash": new_hash,
            })

    return items_to_embed, skipped


def _collect_thread_items(graph: Any) -> Tuple[List[Dict[str, Any]], int]:
    """Collect Thread nodes needing embedding vs skipped."""
    res = graph.query("MATCH (th:Thread) RETURN th.id, th.text, th.text_hash, th.embedding IS NOT NULL")
    items_to_embed = []
    skipped = 0

    for row in res.result_set:
        th_id = row[0]
        text = row[1] or ""
        stored_hash = row[2] or ""
        has_embedding = bool(row[3])

        embed_text = text
        new_hash = hashlib.sha256(embed_text.encode("utf-8")).hexdigest()

        if has_embedding and stored_hash == new_hash:
            skipped += 1
        else:
            items_to_embed.append({
                "id": th_id,
                "text": embed_text,
                "text_hash": new_hash,
            })

    return items_to_embed, skipped


def _embed_and_save_label(
    graph: Any,
    label: str,
    items: List[Dict[str, Any]],
    settings: Settings,
    batch_size: int = 20,
) -> int:
    """Compute embeddings in batches and update FalkorDB nodes."""
    if not items:
        return 0

    print(f"Generating embeddings for {len(items)} {label} nodes in batches of {batch_size}...", flush=True)
    embedded_count = 0

    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        texts = [item["text"] for item in chunk]

        # Call Gemini embedding API
        vectors = embed_documents(texts, settings=settings)

        # Prepare update batch
        update_batch = [
            {
                "id": chunk[j]["id"],
                "vec": vectors[j],
                "text_hash": chunk[j]["text_hash"],
            }
            for j in range(len(chunk))
        ]

        # Save to FalkorDB
        query_str = f"""
        UNWIND $batch AS item
        MATCH (n:{label} {{id: item.id}})
        SET n.embedding = vecf32(item.vec),
            n.text_hash = item.text_hash
        """
        graph.query(query_str, {"batch": update_batch})
        embedded_count += len(chunk)
        print(f"  {label}: saved {embedded_count}/{len(items)}", flush=True)

    return embedded_count


def run_embed(graph: Optional[Any] = None, settings: Optional[Settings] = None) -> Dict[str, Dict[str, int]]:
    """Execute embedding pipeline across Doc, Decision, and Thread nodes."""
    target_graph = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    print("\n=============================================")
    print("RUNNING EMBEDDING PIPELINE")
    print(f"Model: {cfg.GEMINI_EMBED_MODEL} | Dimension: {cfg.EMBED_DIM}")
    print("=============================================", flush=True)

    # 1. Collect items for Doc
    doc_items, doc_skipped = _collect_doc_items(target_graph)
    doc_embedded = _embed_and_save_label(target_graph, "Doc", doc_items, cfg)

    # 2. Collect items for Decision
    dec_items, dec_skipped = _collect_decision_items(target_graph)
    dec_embedded = _embed_and_save_label(target_graph, "Decision", dec_items, cfg)

    # 3. Collect items for Thread
    th_items, th_skipped = _collect_thread_items(target_graph)
    th_embedded = _embed_and_save_label(target_graph, "Thread", th_items, cfg)

    total_embedded = doc_embedded + dec_embedded + th_embedded
    total_skipped = doc_skipped + dec_skipped + th_skipped

    # 4. Print summary table
    print("\n" + "=" * 45)
    print("Embedding Ingestion Summary")
    print("=" * 45)
    print(f"{'Label':<15} {'Embedded':>12} {'Skipped':>12}")
    print("-" * 45)
    print(f"{'Doc':<15} {doc_embedded:>12} {doc_skipped:>12}")
    print(f"{'Decision':<15} {dec_embedded:>12} {dec_skipped:>12}")
    print(f"{'Thread':<15} {th_embedded:>12} {th_skipped:>12}")
    print("-" * 45)
    print(f"{'TOTAL':<15} {total_embedded:>12} {total_skipped:>12}")
    print("=" * 45 + "\n", flush=True)

    return {
        "Doc": {"embedded": doc_embedded, "skipped": doc_skipped},
        "Decision": {"embedded": dec_embedded, "skipped": dec_skipped},
        "Thread": {"embedded": th_embedded, "skipped": th_skipped},
        "Total": {"embedded": total_embedded, "skipped": total_skipped},
    }


if __name__ == "__main__":
    run_embed()

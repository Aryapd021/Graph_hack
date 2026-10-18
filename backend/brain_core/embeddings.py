"""Gemini embedding services for Company Brain.

Per ARCHITECTURE.md sections 5, 6, 7, 19:
- Uses google-genai SDK with GEMINI_EMBED_MODEL and EMBED_DIM.
- Provides embed_query(text) for query-time vector search (task_type='RETRIEVAL_QUERY').
- Provides embed_documents(texts) for batch ingestion indexing (task_type='RETRIEVAL_DOCUMENT').
- Handles exponential backoff retries on rate limits (429) and server errors (5xx).
- Strictly validates that all returned vectors match EMBED_DIM.
"""

import time
from typing import List, Optional

from google import genai
from google.genai import types

from brain_core.config import Settings, get_settings


def get_genai_client(settings: Optional[Settings] = None) -> genai.Client:
    """Initialize and return google-genai Client using configured API key."""
    cfg = settings or get_settings()
    return genai.Client(api_key=cfg.GEMINI_API_KEY)


def _call_embed_with_retry(
    client: genai.Client,
    model: str,
    contents: List[str],
    task_type: Optional[str],
    output_dimensionality: int,
    max_retries: int = 5,
) -> List[List[float]]:
    """Execute embed_content call with exponential backoff on 429/5xx errors."""
    config_kwargs = {"output_dimensionality": output_dimensionality}
    if task_type:
        config_kwargs["task_type"] = task_type

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            res = client.models.embed_content(
                model=model,
                contents=contents,
                config=types.EmbedContentConfig(**config_kwargs),
            )
            if not res.embeddings:
                raise ValueError("Gemini embed_content returned no embeddings")

            vectors: List[List[float]] = []
            for i, emb in enumerate(res.embeddings):
                if not emb.values:
                    raise ValueError(f"Embedding at index {i} returned empty vector")
                vec = list(emb.values)
                if len(vec) != output_dimensionality:
                    raise ValueError(
                        f"Vector length mismatch: expected EMBED_DIM={output_dimensionality}, "
                        f"got {len(vec)} for item at index {i}"
                    )
                vectors.append(vec)
            return vectors

        except Exception as exc:
            last_error = exc
            error_str = str(exc).lower()

            # Check if task_type was rejected
            if task_type and ("task_type" in error_str or "invalid argument" in error_str):
                print(f"Warning: task_type='{task_type}' rejected by SDK. Retrying without task_type...")
                return _call_embed_with_retry(
                    client=client,
                    model=model,
                    contents=contents,
                    task_type=None,
                    output_dimensionality=output_dimensionality,
                    max_retries=max_retries,
                )

            # Retry on rate limiting (429) or transient 5xx server errors
            is_transient = (
                "429" in error_str
                or "resource_exhausted" in error_str
                or "500" in error_str
                or "503" in error_str
                or "unavailable" in error_str
                or "rate limit" in error_str
            )
            if attempt < max_retries - 1 and is_transient:
                # For 429 quota exhaustion, wait longer to let the 60s quota window reset
                if "429" in error_str or "resource_exhausted" in error_str or "quota" in error_str:
                    sleep_s = min(15 * (attempt + 1), 65)
                else:
                    sleep_s = 2 ** attempt
                print(f"Transient error in embed_content ({exc}). Retrying in {sleep_s}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(sleep_s)
            else:
                break

    raise RuntimeError(f"embed_content failed after {max_retries} attempts: {last_error}") from last_error


def embed_query(text: str, settings: Optional[Settings] = None) -> List[float]:
    """Compute embedding vector for a retrieval search query.

    Why: ARCHITECTURE.md B4 row requires embed_query(text) helper in brain_core/embeddings.py
    using task_type='RETRIEVAL_QUERY' and output_dimensionality=EMBED_DIM.
    """
    cfg = settings or get_settings()
    client = get_genai_client(cfg)
    vectors = _call_embed_with_retry(
        client=client,
        model=cfg.GEMINI_EMBED_MODEL,
        contents=[text],
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=cfg.EMBED_DIM,
    )
    return vectors[0]


def embed_documents(texts: List[str], settings: Optional[Settings] = None) -> List[List[float]]:
    """Compute embeddings for a batch of documents to be stored in the graph.

    Why: ARCHITECTURE.md Section 7 & B4 requires stored text embeddings to use
    task_type='RETRIEVAL_DOCUMENT' and output_dimensionality=EMBED_DIM.
    """
    if not texts:
        return []
    cfg = settings or get_settings()
    client = get_genai_client(cfg)
    return _call_embed_with_retry(
        client=client,
        model=cfg.GEMINI_EMBED_MODEL,
        contents=texts,
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=cfg.EMBED_DIM,
    )

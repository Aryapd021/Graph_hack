"""Agent execution loop for conversational reasoning over FalkorDB via MCP.

Per ARCHITECTURE.md Section 12, 13, 14 & Task B8:
- google-genai with GEMINI_MODEL, GEMINI_THINKING_LEVEL, automatic function calling DISABLED.
- Appends the model's response content to the conversation UNCHANGED so thought signatures are preserved.
- Executes every function call in order, records TraceStep, accumulates evidence and graph.
- Function responses to Gemini contain only {summary, data, evidence} with date enrichment applied.
- At most AGENT_MAX_STEPS tool rounds; on step cap, requests final answer with tools disabled.
- History: at most 10 prior turns from ChatRequest.
- Timeouts: LLM_TIMEOUT_S per Gemini call; maps Gemini errors to 502 LLM_ERROR.
- Citation validation: filters [[node_id]] markers against collected evidence.
- Highlight: cited IDs + connection path nodes and edges.
"""

import asyncio
import copy
import datetime
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from google import genai
from google.genai import types

from brain_api.agent.mcp_client import call_tool, get_tool_declarations
from brain_api.agent.prompts import SYSTEM_PROMPT
from brain_api.exceptions import LLMErrorException
from brain_core.config import Settings, get_settings
from brain_core.models import (
    ChatRequest,
    ChatResponse,
    Evidence,
    GraphEdge,
    GraphNode,
    GraphPayload,
    Highlight,
    TraceStep,
)

logger = logging.getLogger("brain_api.agent.loop")


def enrich_dates(obj: Any) -> Any:
    """Recursively add a <key>_utc_date sibling ('YYYY-MM-DD') for every integer field

    whose key ends in '_at' or equals 'last_active'.
    Leaves original epoch integers intact.
    """
    if isinstance(obj, dict):
        new_dict: Dict[str, Any] = {}
        for k, v in obj.items():
            new_dict[k] = enrich_dates(v)
            if (k.endswith("_at") or k == "last_active") and isinstance(v, (int, float)) and v is not None:
                try:
                    dt = datetime.datetime.fromtimestamp(int(v), tz=datetime.timezone.utc)
                    new_dict[f"{k}_utc_date"] = dt.strftime("%Y-%m-%d")
                except (ValueError, OSError, OverflowError):
                    pass
        return new_dict
    elif isinstance(obj, list):
        return [enrich_dates(item) for item in obj]
    else:
        return obj


def validate_citations(text: str, evidence: List[Evidence]) -> Tuple[str, List[Evidence]]:
    """Filter citation markers [[node_id]] in answer text.

    Keeps only markers whose node_id is in evidence.
    Removes unknown markers from text.
    Builds citations list from valid cited evidence in order of appearance (deduped).
    """
    evidence_map = {ev.node_id: ev for ev in evidence}
    cited_evidence: List[Evidence] = []
    seen_ids: Set[str] = set()

    def replace_marker(match: re.Match) -> str:
        marker_id = match.group(1).strip()
        if marker_id in evidence_map:
            if marker_id not in seen_ids:
                seen_ids.add(marker_id)
                cited_evidence.append(evidence_map[marker_id])
            return f"[[{marker_id}]]"
        return ""

    cleaned = re.sub(r"\[\[(.*?)\]\]", replace_marker, text)
    # Normalize leftover whitespace and spacing before punctuation
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" \.", ".", cleaned)
    cleaned = re.sub(r" ,", ",", cleaned)
    return cleaned.strip(), cited_evidence


async def _call_gemini_with_retry(
    ai_client: Any,
    model: str,
    contents: List[Any],
    config: Any,
    timeout_s: float,
) -> Any:
    """Call Gemini generate_content with backoff retry on 429 within the timeout budget."""
    deadline = time.time() + timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise LLMErrorException(f"Gemini API request timed out after {timeout_s}s")
        try:
            return await asyncio.wait_for(
                ai_client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            raise LLMErrorException(f"Gemini API request timed out after {timeout_s}s") from exc
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                delay = 5.5
                match = re.search(r"retry in (\d+(?:\.\d+)?)s", msg)
                if match:
                    try:
                        delay = float(match.group(1)) + 0.5
                    except ValueError:
                        pass
                logger.warning(f"Gemini 429 rate limit hit; backing off for {delay:.1f}s...")
                if delay > 65:
                    raise LLMErrorException(f"Gemini API rate limited: {exc}") from exc
                await asyncio.sleep(delay)
                continue
            raise LLMErrorException(f"Gemini API call failed: {exc}") from exc


async def execute_agent_loop(
    request: ChatRequest,
    settings: Optional[Settings] = None,
    client: Optional[genai.Client] = None,
) -> ChatResponse:
    """Execute the multi-turn agent tool-calling loop for a chat query."""
    cfg = settings or get_settings()

    if client is None:
        if not cfg.GEMINI_API_KEY:
            raise LLMErrorException("GEMINI_API_KEY is not configured")
        ai_client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    else:
        ai_client = client

    # 1. Fetch available MCP tool declarations
    tool_declarations = await get_tool_declarations()
    gemini_tools = [types.Tool(function_declarations=tool_declarations)]

    # 2. Build initial conversation contents
    contents: List[types.Content] = []

    # Prior history: at most 10 turns
    history_turns = request.history[-10:] if request.history else []
    for turn in history_turns:
        role = "user" if turn.role == "user" else "model"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=turn.content)],
            )
        )

    # Current user message
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=request.message)],
        )
    )

    # Reasoning state accumulation
    trace: List[TraceStep] = []
    accumulated_evidence: Dict[str, Evidence] = {}
    accumulated_nodes: Dict[str, GraphNode] = {}
    accumulated_edges: Dict[str, GraphEdge] = {}
    path_node_ids: List[str] = []
    path_edge_ids: List[str] = []

    final_answer_text = ""
    max_steps = cfg.AGENT_MAX_STEPS
    step_count = 0

    thinking_level = cfg.GEMINI_THINKING_LEVEL.lower() if cfg.GEMINI_THINKING_LEVEL else "low"
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=gemini_tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
    )

    # 3. Main multi-turn reasoning loop
    while step_count < max_steps:
        response = await _call_gemini_with_retry(
            ai_client=ai_client,
            model=cfg.GEMINI_MODEL,
            contents=contents,
            config=config,
            timeout_s=float(cfg.LLM_TIMEOUT_S),
        )

        if not response or not response.candidates:
            break

        candidate = response.candidates[0]
        # Append model response content UNCHANGED so thought signatures are preserved
        contents.append(candidate.content)

        # Check if the model requested function calls
        function_calls = response.function_calls
        if not function_calls:
            # Model generated direct textual answer
            final_answer_text = response.text or ""
            break

        # Execute all function calls requested in this turn
        fn_response_parts: List[types.Part] = []

        for call in function_calls:
            step_count += 1
            tool_name = call.name
            tool_args = call.args or {}

            t0 = time.perf_counter()
            tool_result = await call_tool(name=tool_name, args=tool_args)
            duration_ms = int((time.perf_counter() - t0) * 1000)

            # Record TraceStep
            step = TraceStep(
                step=step_count,
                tool=tool_name,
                args=tool_args,
                ok=tool_result.ok,
                summary=tool_result.summary,
                cypher_ids=tool_result.cypher_ids,
                duration_ms=duration_ms,
            )
            trace.append(step)

            # Accumulate evidence (deduped by node_id)
            for ev in tool_result.evidence:
                accumulated_evidence[ev.node_id] = ev

            # Accumulate graph nodes and edges (union by id)
            for n in tool_result.graph.nodes:
                accumulated_nodes[n.id] = n
            for e in tool_result.graph.edges:
                accumulated_edges[e.id] = e

            # Accumulate connection_path highlights
            if tool_name == "connection_path" and "path" in tool_result.data:
                for item in tool_result.data.get("path", []):
                    if isinstance(item, dict) and "node" in item:
                        node_val = item["node"]
                        nid = getattr(node_val, "node_id", None) or (
                            node_val.get("node_id") if isinstance(node_val, dict) else None
                        )
                        if nid:
                            path_node_ids.append(nid)
                for e in tool_result.graph.edges:
                    path_edge_ids.append(e.id)

            # Prepare enriched function response payload for Gemini
            enriched_data = enrich_dates(copy.deepcopy(tool_result.data))
            fn_payload = {
                "summary": tool_result.summary,
                "data": enriched_data,
                "evidence": [ev.model_dump() for ev in tool_result.evidence],
            }
            fn_response_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=fn_payload,
                )
            )

            if step_count >= max_steps:
                break

        # Append function responses as a tool content turn (Gemini requires role="user")
        contents.append(
            types.Content(
                role="user",
                parts=fn_response_parts,
            )
        )

    # 4. If step cap reached without final text, force answer with tools disabled
    if not final_answer_text and step_count >= max_steps:
        logger.info(f"Step cap reached ({max_steps}); forcing final answer with tools disabled.")
        force_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
        )
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="Please provide your final answer now based only on the tool results gathered above."
                    )
                ],
            )
        )
        force_res = await _call_gemini_with_retry(
            ai_client=ai_client,
            model=cfg.GEMINI_MODEL,
            contents=contents,
            config=force_config,
            timeout_s=float(cfg.LLM_TIMEOUT_S),
        )
        final_answer_text = force_res.text or ""

    # 5. Citation validation
    all_evidence = list(accumulated_evidence.values())
    validated_answer, validated_citations = validate_citations(
        text=final_answer_text,
        evidence=all_evidence,
    )

    # 6. Highlight computation
    cited_ids = [ev.node_id for ev in validated_citations]
    combined_highlight_nodes: List[str] = list(dict.fromkeys(cited_ids + path_node_ids))
    combined_highlight_edges: List[str] = list(dict.fromkeys(path_edge_ids))

    highlight = Highlight(
        node_ids=combined_highlight_nodes,
        edge_ids=combined_highlight_edges,
    )

    # 7. Assemble final ChatResponse
    return ChatResponse(
        answer=validated_answer,
        citations=validated_citations,
        trace=trace,
        graph=GraphPayload(
            nodes=list(accumulated_nodes.values()),
            edges=list(accumulated_edges.values()),
        ),
        highlight=highlight,
    )

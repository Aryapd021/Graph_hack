"""Tests for B4: embeddings pipeline and helpers."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from brain_core.config import Settings
from brain_core.embeddings import _call_embed_with_retry, embed_documents, embed_query
from ingest.embed import (
    _collect_decision_items,
    _collect_doc_items,
    _collect_thread_items,
    run_embed,
)


def test_text_formatting_and_hash():
    """Verify exact text concatenation and sha256 hashing per spec."""
    # Doc = display + newline + body
    doc_text = "FastAPI Intro\nA high performance web framework."
    expected_doc_hash = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()
    assert len(expected_doc_hash) == 64

    # Decision = display + newline + summary + newline + rationale
    dec_text = "ADR-001\nAdopt FalkorDB\nNative graph with vector indices"
    expected_dec_hash = hashlib.sha256(dec_text.encode("utf-8")).hexdigest()
    assert len(expected_dec_hash) == 64

    # Thread = text
    th_text = "Hey team, what do we think of the new schema?"
    expected_th_hash = hashlib.sha256(th_text.encode("utf-8")).hexdigest()
    assert len(expected_th_hash) == 64


def test_collect_doc_items_skips_embedded():
    """Test that items with matching hash and existing embedding are skipped."""
    mock_graph = MagicMock()
    # row format: [d.id, d.display, d.body, d.text_hash, has_embedding]
    doc_text = "Doc 1\nBody 1"
    matching_hash = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()

    mock_graph.query.return_value.result_set = [
        ["doc_1", "Doc 1", "Body 1", matching_hash, True],       # skip
        ["doc_2", "Doc 2", "Body 2", "old_hash", True],          # re-embed (hash changed)
        ["doc_3", "Doc 3", "Body 3", matching_hash, False],      # embed (no embedding yet)
    ]

    items, skipped = _collect_doc_items(mock_graph)
    assert skipped == 1
    assert len(items) == 2
    assert items[0]["id"] == "doc_2"
    assert items[1]["id"] == "doc_3"


def test_dimension_validation_failure():
    """Fail with clear message if returned vector length is not EMBED_DIM."""
    mock_client = MagicMock()
    mock_embedding = MagicMock()
    # Return 128-dim vector instead of 3072
    mock_embedding.values = [0.1] * 128
    mock_res = MagicMock()
    mock_res.embeddings = [mock_embedding]
    mock_client.models.embed_content.return_value = mock_res

    with pytest.raises(RuntimeError) as exc_info:
        _call_embed_with_retry(
            client=mock_client,
            model="gemini-embedding-001",
            contents=["test text"],
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=3072,
            max_retries=1,
        )
    assert "Vector length mismatch" in str(exc_info.value)
    assert "expected EMBED_DIM=3072, got 128" in str(exc_info.value)


def test_dimension_validation_success():
    """Succeed when returned vector length matches EMBED_DIM."""
    mock_client = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.05] * 3072
    mock_res = MagicMock()
    mock_res.embeddings = [mock_embedding]
    mock_client.models.embed_content.return_value = mock_res

    vectors = _call_embed_with_retry(
        client=mock_client,
        model="gemini-embedding-001",
        contents=["test text"],
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=3072,
        max_retries=1,
    )
    assert len(vectors) == 1
    assert len(vectors[0]) == 3072


def test_embed_documents_and_query_task_types():
    """Verify task_type parameters passed to genai client."""
    with patch("brain_core.embeddings.get_genai_client") as mock_get_client, \
         patch("brain_core.embeddings._call_embed_with_retry") as mock_call:
        mock_call.return_value = [[0.1] * 3072]
        
        embed_query("search query")
        assert mock_call.call_args[1]["task_type"] == "RETRIEVAL_QUERY"

        embed_documents(["doc text"])
        assert mock_call.call_args[1]["task_type"] == "RETRIEVAL_DOCUMENT"

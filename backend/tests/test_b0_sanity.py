"""Sanity and verification tests for B0 deliverables."""

import pytest
from brain_core.config import Settings, IngestSettings, get_settings


def test_test_safety_settings_loaded() -> None:
    """Verify that settings are loaded with the test graph suffix and safe host."""
    settings = get_settings()
    assert settings.FALKORDB_GRAPH.endswith("_test")
    assert settings.FALKORDB_HOST in {"localhost", "127.0.0.1", "falkordb"}
    assert settings.FALKORDB_USERNAME is None
    assert settings.FALKORDB_PASSWORD is None


def test_config_strict_booleans() -> None:
    """Verify that boolean settings reject non-boolean / loose strings."""
    with pytest.raises(ValueError):
        Settings(
            GEMINI_API_KEY="test",
            GEMINI_MODEL="gemini-3.8-flash",
            GEMINI_EMBED_MODEL="gemini-embedding-001",
            EMBED_DIM=3072,
            GITHUB_REPO="fastapi/fastapi",
            FALKORDB_SSL="yes",  # Invalid: must be 'true' or 'false'
        )


def test_config_github_repo_validation() -> None:
    """Verify that GITHUB_REPO validates owner/name format."""
    with pytest.raises(ValueError):
        Settings(
            GEMINI_API_KEY="test",
            GEMINI_MODEL="gemini-3.8-flash",
            GEMINI_EMBED_MODEL="gemini-embedding-001",
            EMBED_DIM=3072,
            GITHUB_REPO="invalid_no_slash",
        )


def test_ingest_settings_module_rules_parsing() -> None:
    """Verify MODULE_RULES JSON parsing and validation."""
    valid_rules_json = '[{"prefix":"fastapi/","depth":1}]'
    ingest = IngestSettings(
        GEMINI_API_KEY="test",
        GEMINI_MODEL="gemini-3.8-flash",
        GEMINI_EMBED_MODEL="gemini-embedding-001",
        EMBED_DIM=3072,
        GITHUB_REPO="fastapi/fastapi",
        PSEUDONYM_SALT="test-salt",
        MODULE_RULES=valid_rules_json,
    )
    assert len(ingest.MODULE_RULES) == 1
    assert ingest.MODULE_RULES[0].prefix == "fastapi/"
    assert ingest.MODULE_RULES[0].depth == 1

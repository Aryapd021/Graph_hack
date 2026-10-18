"""Configuration management for Company Brain using pydantic-settings.

Per ARCHITECTURE.md sections 2, 4, 5:
- Environment variables are read ONLY in this file.
- Dotenv path is determined by ENV_FILE (default '.env').
- Core settings are always required.
- Ingest-only settings are loaded separately via get_ingest_settings().
- Fail-fast validation with detailed per-variable error messages.
"""

import json
import os
import re
from functools import lru_cache
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModuleRule(BaseModel):
    """Rule defining source code / doc module prefixes and depth boundaries."""

    prefix: str
    depth: int = Field(ge=0)

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        """Validate that module prefix ends with a forward slash as required by spec."""
        # Why: Section 5 requires prefixes in MODULE_RULES to end with '/' for strict directory matching
        if not v.endswith("/"):
            raise ValueError(f"ModuleRule prefix must end with '/', got '{v}'")
        return v


def _parse_strict_bool(v: Any, field_name: str) -> bool:
    """Strictly validate boolean string representation.

    Accepts only True, False, 'true', or 'false' (case-insensitive).
    Rejects loose truthy values like '1', 'yes', '0', 'no'.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        cleaned = v.strip().lower()
        if cleaned == "true":
            return True
        if cleaned == "false":
            return False
    # Why: Section 5 explicitly mandates that boolean vars accept only true/false
    raise ValueError(f"{field_name} accepts only 'true' or 'false', got '{v}'")


def _normalize_optional_str(v: Any) -> Optional[str]:
    """Normalize empty string or whitespace-only values to None."""
    if v is None:
        return None
    if isinstance(v, str):
        stripped = v.strip()
        # Why: Section 5 specifies empty username or password means None
        return stripped if stripped else None
    return str(v)


def _resolve_env_file() -> str:
    """Resolve dotenv path from ENV_FILE or locate .env in cwd or parent directory.

    Why: Allows scripts and tests to run cleanly from either repo root or backend/ directory.
    """
    target = os.getenv("ENV_FILE")
    if target:
        if os.path.exists(target):
            return target
        parent_target = os.path.join("..", target)
        if os.path.exists(parent_target):
            return parent_target
        return target

    if os.path.exists(".env"):
        return ".env"
    if os.path.exists("../.env"):
        return "../.env"
    return ".env"


class Settings(BaseSettings):
    """Core settings required for runtime operation of Company Brain."""

    # FalkorDB connection settings
    FALKORDB_HOST: str = "falkordb"
    FALKORDB_PORT: int = 6379
    FALKORDB_USERNAME: Optional[str] = None
    FALKORDB_PASSWORD: Optional[str] = None
    FALKORDB_SSL: bool = False
    FALKORDB_GRAPH: str = "company_brain"

    # Gemini configuration
    GEMINI_API_KEY: str
    GEMINI_MODEL: str
    GEMINI_EMBED_MODEL: str
    EMBED_DIM: int
    GEMINI_THINKING_LEVEL: Literal["low", "medium", "high"] = "low"
    LLM_TIMEOUT_S: int = 45

    # Target repository
    GITHUB_REPO: str

    # Behavior settings
    STALE_PR_THRESHOLD: int = 1
    AGENT_MAX_STEPS: int = 8
    API_PORT: int = 8000
    SERVE_STATIC: bool = False
    DEMO_MODE: bool = True
    ENABLE_INGEST_REFRESH: bool = True
    CHAT_RATE_LIMIT_PER_MIN: int = 10

    # Why: ENV_FILE environment variable determines which dotenv file to read (.env or .env.cloud)
    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("FALKORDB_HOST", mode="before")
    @classmethod
    def clean_host(cls, v: Any) -> str:
        """Strip protocol or trailing port if included in FALKORDB_HOST."""
        if isinstance(v, str):
            cleaned = v.strip()
            # Why: Strip protocol prefix if user pasted a redis(s):// string
            if "://" in cleaned:
                cleaned = cleaned.split("://")[-1]
            # Why: Strip trailing port if user pasted host:port so socket resolution doesn't duplicate port
            if ":" in cleaned:
                cleaned = cleaned.split(":")[0]
            return cleaned
        return str(v)

    @field_validator("FALKORDB_USERNAME", "FALKORDB_PASSWORD", mode="before")
    @classmethod
    def clean_credentials(cls, v: Any) -> Optional[str]:
        """Convert empty credentials to None."""
        return _normalize_optional_str(v)

    @field_validator("FALKORDB_SSL", "SERVE_STATIC", "DEMO_MODE", "ENABLE_INGEST_REFRESH", mode="before")
    @classmethod
    def validate_booleans(cls, v: Any, info: Any) -> bool:
        """Validate strict booleans ('true'/'false')."""
        return _parse_strict_bool(v, info.field_name)

    @field_validator("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_EMBED_MODEL", mode="before")
    @classmethod
    def validate_non_empty_strings(cls, v: Any, info: Any) -> str:
        """Validate that core Gemini settings are non-empty strings."""
        if not v or not str(v).strip():
            # Why: Gemini API calls will fail immediately if keys or model identifiers are missing
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return str(v).strip()

    @field_validator("EMBED_DIM")
    @classmethod
    def validate_embed_dim(cls, v: int) -> int:
        """Validate that embedding dimension is a positive integer."""
        if v <= 0:
            # Why: Vector index creation in FalkorDB requires a strictly positive dimension
            raise ValueError(f"EMBED_DIM must be a positive integer, got {v}")
        return v

    @field_validator("CHAT_RATE_LIMIT_PER_MIN")
    @classmethod
    def validate_rate_limit(cls, v: int) -> int:
        """Validate that chat rate limit is a positive integer."""
        if v <= 0:
            raise ValueError(f"CHAT_RATE_LIMIT_PER_MIN must be a positive integer, got {v}")
        return v

    @field_validator("GITHUB_REPO")
    @classmethod
    def validate_github_repo(cls, v: str) -> str:
        """Validate GitHub repository format 'owner/name'."""
        cleaned = v.strip()
        # Why: Section 5 explicitly requires GITHUB_REPO to match '^[\w.-]+/[\w.-]+$'
        pattern = r"^[\w.-]+/[\w.-]+$"
        if not re.match(pattern, cleaned):
            raise ValueError(
                f"GITHUB_REPO must match format 'owner/name' with pattern {pattern}, got '{cleaned}'"
            )
        return cleaned

    @field_validator("API_PORT", mode="before")
    @classmethod
    def allow_port_override(cls, v: Any) -> int:
        """Allow host PORT environment variable to override API_PORT if set."""
        # Why: Section 5 specifies 'the host's PORT variable overrides this when set' (e.g. Railway)
        port_override = os.getenv("PORT")
        if port_override:
            try:
                return int(port_override)
            except ValueError:
                pass
        return int(v) if v is not None else 8000


class IngestSettings(Settings):
    """Settings required for the ingestion pipeline and synthetic data generation."""

    GITHUB_TOKEN: Optional[str] = None
    MAX_PRS: int = 150
    MAX_DOCS: int = 40
    MAX_DOC_CHARS: int = 6000
    MODULE_RULES: List[ModuleRule] = Field(
        default_factory=lambda: [
            ModuleRule(prefix="fastapi/", depth=1),
            ModuleRule(prefix="docs/en/docs/", depth=1),
            ModuleRule(prefix="tests/", depth=1),
        ]
    )
    DOC_PATH_PREFIXES: str = "docs/en/docs/"
    DOC_EXCLUDE: str = "people,sponsors,release-notes,external-links,newsletter,contributing"
    SKIP_BOT_PRS: bool = True

    # Synthetic data generator parameters
    PSEUDONYM_SALT: str
    SYNTH_SEED: int = 42
    SYNTH_TEAMS: int = 4
    SYNTH_DECISIONS: int = 12
    SYNTH_EXTRA_TICKETS: int = 10
    SYNTH_EXTRA_THREADS: int = 12

    @field_validator("GITHUB_TOKEN", mode="before")
    @classmethod
    def clean_github_token(cls, v: Any) -> Optional[str]:
        """Convert empty GitHub token string to None."""
        return _normalize_optional_str(v)

    @field_validator("SKIP_BOT_PRS", mode="before")
    @classmethod
    def validate_skip_bots(cls, v: Any) -> bool:
        """Validate strict boolean for SKIP_BOT_PRS."""
        return _parse_strict_bool(v, "SKIP_BOT_PRS")

    @field_validator("PSEUDONYM_SALT", mode="before")
    @classmethod
    def validate_salt(cls, v: Any) -> str:
        """Validate that pseudonymization salt is non-empty."""
        if not v or not str(v).strip():
            # Why: Decision D5 requires deterministic pseudonymization using PSEUDONYM_SALT
            raise ValueError("PSEUDONYM_SALT must be a non-empty string")
        return str(v).strip()

    @field_validator("MAX_PRS", "MAX_DOCS", "MAX_DOC_CHARS")
    @classmethod
    def validate_positive_limits(cls, v: int, info: Any) -> int:
        """Validate positive ingestion limits."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer, got {v}")
        return v

    @field_validator("MODULE_RULES", mode="before")
    @classmethod
    def parse_module_rules(cls, v: Any) -> Any:
        """Parse MODULE_RULES from JSON string or list of dicts.

        Why: Section 5 specifies MODULE_RULES parses as a JSON list of {prefix: str ending in '/', depth: int >= 0}.
        """
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError as err:
                raise ValueError(f"MODULE_RULES is not valid JSON: {err}") from err
            return parsed
        return v


def _format_validation_error(exc: ValidationError) -> str:
    """Format Pydantic ValidationError into a clean list naming each bad variable."""
    error_messages = []
    for err in exc.errors():
        # Why: Extract exact variable name for clear fail-fast diagnostic
        loc = ".".join(str(item) for item in err["loc"])
        msg = err["msg"]
        error_messages.append(f"  - {loc}: {msg}")
    return "\n".join(error_messages)


@lru_cache()
def get_settings() -> Settings:
    """Load, validate, and cache core application settings.

    Fails fast if any required core setting is missing or invalid.
    """
    try:
        return Settings()
    except ValidationError as exc:
        details = _format_validation_error(exc)
        # Why: Section 5 requires failing fast with a message naming each bad variable
        raise ValueError(f"Core configuration validation failed:\n{details}") from exc


@lru_cache()
def get_ingest_settings() -> IngestSettings:
    """Load, validate, and cache ingestion pipeline settings.

    Fails fast if any required ingestion setting (e.g., PSEUDONYM_SALT) is missing or invalid.
    """
    try:
        return IngestSettings()
    except ValidationError as exc:
        details = _format_validation_error(exc)
        # Why: Section 5 requires failing fast with a message naming each bad variable
        raise ValueError(f"Ingest configuration validation failed:\n{details}") from exc

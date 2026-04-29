"""Environment-driven configuration."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ShimMode(StrEnum):
    PROXY = "proxy"
    HIJACK = "hijack"
    LOCAL_ONLY = "local-only"


class Settings(BaseSettings):
    """Single source of truth for runtime configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore", case_sensitive=False)

    # ---- shim ---------------------------------------------------------------
    mode: ShimMode = Field(default=ShimMode.PROXY, alias="SHIM_MODE")
    host: str = Field(default="0.0.0.0", alias="SHIM_HOST")
    port: int = Field(default=8787, alias="SHIM_PORT")
    log_level: str = Field(default="info", alias="SHIM_LOG_LEVEL")
    max_local_request_bytes: int = Field(default=131_072, alias="SHIM_MAX_LOCAL_REQUEST_BYTES")
    upstream_base_url: str = Field(default="https://app.warp.dev", alias="UPSTREAM_BASE_URL")

    # ---- litellm ------------------------------------------------------------
    litellm_base_url: str = Field(default="http://litellm:4000/v1", alias="LITELLM_BASE_URL")
    litellm_master_key: str = Field(default="sk-harp", alias="LITELLM_MASTER_KEY")

    # ---- model selection (used in chat-completion calls) --------------------
    local_primary_model: str = Field(default="local-primary", alias="LITELLM_LOCAL_MODEL_NAME")
    frontier_fallback_model: str = Field(
        default="frontier-fallback", alias="LITELLM_FRONTIER_MODEL_NAME"
    )

    # ---- behaviour ----------------------------------------------------------
    enable_frontier_improver: bool = Field(default=False, alias="ENABLE_FRONTIER_IMPROVER")

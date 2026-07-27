from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LLMProviderName = Literal["fake", "openai-compatible", "openai-responses", "codex-bridge"]


class LLMConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProviderName
    base_url: str | None = None
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


class LLMConfigResponse(BaseModel):
    provider: LLMProviderName
    base_url: str | None = None
    model: str
    has_api_key: bool
    source: Literal["env", "runtime"]


class LLMTestResponse(BaseModel):
    ok: bool
    provider: LLMProviderName
    model: str
    base_url: str | None = None
    error: str | None = None

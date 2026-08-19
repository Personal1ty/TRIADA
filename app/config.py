from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["fake", "openai-compatible", "openai-responses", "codex-bridge"] = "fake"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "fake-devops-model"
    database_url: str = "sqlite+aiosqlite:///./triada.db"
    memory_retrieval_backend: Literal["lexical", "pgvector"] = "lexical"
    memory_embedding_dimensions: int = Field(default=64, ge=8, le=2048)
    redis_url: str | None = None
    capture_reasoning_summary: bool = True
    pass_reasoning_summary_to_auditor: bool = True
    event_output_dir: str = ".triada/artifacts"
    llm_config_path: str = ".triada/secrets/llm_config.enc"
    llm_secret_key_path: str = ".triada/secrets/llm_config.key"
    shell_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    worker_llm_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    orchestrator_llm_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    auditor_llm_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    task_execution_timeout_seconds: float = Field(default=300.0, gt=0, le=86_400)
    max_tool_output_bytes: int = Field(default=65536, ge=1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()

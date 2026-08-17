import pytest

from app.config import Settings, get_settings


def test_default_settings_use_fake_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = Settings()
    assert settings.llm_provider == "fake"
    assert settings.capture_reasoning_summary is True
    assert settings.pass_reasoning_summary_to_auditor is True
    assert settings.memory_retrieval_backend == "lexical"
    assert settings.memory_embedding_dimensions == 64


def test_api_key_is_secret_and_not_in_repr(monkeypatch):
    settings = Settings(llm_api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(settings)


def test_get_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_MODEL", "corp-coder")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_provider == "openai-compatible"
    assert settings.llm_model == "corp-coder"

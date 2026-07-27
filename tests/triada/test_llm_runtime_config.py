from pathlib import Path

from app.config import Settings
from app.llm.runtime_config import LLMConfigService, LLMProviderConfig


def test_llm_config_defaults_to_settings_without_leaking_key(tmp_path: Path):
    service = LLMConfigService(
        settings=Settings(
            llm_provider="openai-compatible",
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_model="corp-coder",
            llm_api_key="sk-secret-token",
        ),
        config_path=tmp_path / "llm-config.enc",
        key_path=tmp_path / "llm-config.key",
    )

    public = service.public_config()

    assert public == {
        "provider": "openai-compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "corp-coder",
        "has_api_key": True,
        "source": "env",
    }
    assert "sk-secret-token" not in str(public)


def test_llm_config_persists_api_key_encrypted_at_rest(tmp_path: Path):
    config_path = tmp_path / "llm-config.enc"
    key_path = tmp_path / "llm-config.key"
    service = LLMConfigService(
        settings=Settings(),
        config_path=config_path,
        key_path=key_path,
    )

    service.save(
        LLMProviderConfig(
            provider="openai-compatible",
            base_url="https://deepseek.example/v1",
            model="deepseek-reasoner",
            api_key="sk-runtime-secret",
        )
    )

    stored = config_path.read_text()
    assert "sk-runtime-secret" not in stored
    assert "deepseek-reasoner" not in stored
    assert key_path.exists()

    reloaded = LLMConfigService(settings=Settings(), config_path=config_path, key_path=key_path)
    loaded = reloaded.current_config()
    assert loaded.provider == "openai-compatible"
    assert loaded.base_url == "https://deepseek.example/v1"
    assert loaded.model == "deepseek-reasoner"
    assert loaded.api_key == "sk-runtime-secret"
    assert reloaded.public_config()["has_api_key"] is True
    assert reloaded.public_config()["source"] == "runtime"


def test_llm_config_can_clear_runtime_api_key(tmp_path: Path):
    service = LLMConfigService(
        settings=Settings(llm_api_key="sk-env-secret"),
        config_path=tmp_path / "llm-config.enc",
        key_path=tmp_path / "llm-config.key",
    )

    service.save(
        LLMProviderConfig(
            provider="openai-compatible",
            base_url="http://127.0.0.1:11434/v1",
            model="local-model",
            api_key=None,
        )
    )

    config = service.current_config()
    assert config.api_key is None
    assert service.public_config()["has_api_key"] is False

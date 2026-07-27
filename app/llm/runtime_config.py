from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from app.config import Settings


LLMProviderName = Literal["fake", "openai-compatible", "openai-responses", "codex-bridge"]


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: LLMProviderName
    model: str
    base_url: str | None = None
    api_key: str | None = None
    source: Literal["env", "runtime"] = "runtime"


class LLMConfigService:
    def __init__(
        self,
        *,
        settings: Settings,
        config_path: str | Path,
        key_path: str | Path,
    ) -> None:
        self._settings = settings
        self._config_path = Path(config_path)
        self._key_path = Path(key_path)

    def current_config(self) -> LLMProviderConfig:
        runtime_config = self._load_runtime_config()
        if runtime_config is not None:
            return runtime_config
        return LLMProviderConfig(
            provider=self._settings.llm_provider,
            base_url=self._settings.llm_base_url,
            model=self._settings.llm_model,
            api_key=(
                self._settings.llm_api_key.get_secret_value()
                if self._settings.llm_api_key is not None
                else None
            ),
            source="env",
        )

    def public_config(self) -> dict:
        config = self.current_config()
        return {
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "has_api_key": bool(config.api_key),
            "source": config.source,
        }

    def save(self, config: LLMProviderConfig) -> LLMProviderConfig:
        normalized = LLMProviderConfig(
            provider=config.provider,
            base_url=config.base_url or None,
            model=config.model,
            api_key=config.api_key or None,
            source="runtime",
        )
        payload = {
            "provider": normalized.provider,
            "base_url": normalized.base_url,
            "model": normalized.model,
            "api_key": normalized.api_key,
        }
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(self._encrypt_json(payload), encoding="utf-8")
        try:
            self._config_path.chmod(0o600)
        except OSError:
            pass
        return normalized

    def _load_runtime_config(self) -> LLMProviderConfig | None:
        if not self._config_path.exists():
            return None
        payload = self._decrypt_json(self._config_path.read_text(encoding="utf-8"))
        return LLMProviderConfig(
            provider=payload["provider"],
            base_url=payload.get("base_url"),
            model=payload["model"],
            api_key=payload.get("api_key"),
            source="runtime",
        )

    def _encrypt_json(self, payload: dict) -> str:
        plaintext = json.dumps(payload, sort_keys=True).encode("utf-8")
        nonce = os.urandom(16)
        ciphertext = self._xor_bytes(plaintext, nonce)
        return json.dumps(
            {
                "version": 1,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            },
            sort_keys=True,
        )

    def _decrypt_json(self, encrypted_payload: str) -> dict:
        payload = json.loads(encrypted_payload)
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        plaintext = self._xor_bytes(ciphertext, nonce)
        return json.loads(plaintext.decode("utf-8"))

    def _xor_bytes(self, value: bytes, nonce: bytes) -> bytes:
        key = self._load_or_create_key()
        output = bytearray()
        counter = 0
        while len(output) < len(value):
            block = sha256(key + nonce + counter.to_bytes(8, "big")).digest()
            output.extend(block)
            counter += 1
        return bytes(left ^ right for left, right in zip(value, output, strict=False))

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return base64.b64decode(self._key_path.read_text(encoding="utf-8"))
        key = os.urandom(32)
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")
        try:
            self._key_path.chmod(0o600)
        except OSError:
            pass
        return key

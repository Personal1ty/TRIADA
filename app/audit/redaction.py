import re
from collections.abc import Mapping


_REDACTION = "[REDACTED]"

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|secret[_-]?token|token)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bauthorization\s*:\s*(bearer|basic)\s+([A-Za-z0-9._~+/=-]+)"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)?"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def _mask_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:
        return match.group(0).replace(match.group(match.lastindex), _REDACTION)
    return _REDACTION


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_mask_match, redacted)
    return redacted


def contains_secret(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _SECRET_PATTERNS)


def redact_payload(payload: object) -> object:
    if isinstance(payload, str):
        return redact_text(payload)
    if isinstance(payload, Mapping):
        return {
            redact_payload(key) if isinstance(key, str) else key: redact_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(redact_payload(item) for item in payload)
    return payload

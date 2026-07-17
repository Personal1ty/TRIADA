import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request


API_URL = "https://api.llm.fixmost.com/v1/public/chat/completions"
MODELS_URL = "https://api.llm.fixmost.com/v1/public/models"
MODEL = "corp-coder"
DEFAULT_PROMPT = "Сравни два варианта и дай итоговый ответ."
SEARCH_KEYS = ("thinking", "reasoning", "reasoning_content", "analysis")


def make_cases():
    variants = [
        ("baseline", {}),
        ("think_true", {"think": True}),
        ("thinking_true", {"thinking": True}),
        ("reasoning_true", {"reasoning": True}),
        ("reasoning_effort_low", {"reasoning_effort": "low"}),
        ("reasoning_effort_medium", {"reasoning_effort": "medium"}),
        ("reasoning_effort_high", {"reasoning_effort": "high"}),
        ("thinking_token_budget_256", {"thinking_token_budget": 256}),
        ("thinking_token_budget_1024", {"thinking_token_budget": 1024}),
        ("reasoning_object_medium", {"reasoning": {"effort": "medium"}}),
        (
            "chat_template_kwargs_enable_thinking_true",
            {"chat_template_kwargs": {"enable_thinking": True}},
        ),
        (
            "chat_template_kwargs_enable_thinking_false",
            {"chat_template_kwargs": {"enable_thinking": False}},
        ),
        (
            "extra_body_chat_template_kwargs_enable_thinking_true",
            {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}},
        ),
        (
            "extra_body_chat_template_kwargs_enable_thinking_false",
            {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
        ),
        (
            "extraBody_chat_template_kwargs_enable_thinking_true",
            {"extraBody": {"chat_template_kwargs": {"enable_thinking": True}}},
        ),
        (
            "extraBody_chat_template_kwargs_enable_thinking_false",
            {"extraBody": {"chat_template_kwargs": {"enable_thinking": False}}},
        ),
    ]
    cases = []
    for stream in (False, True):
        for name, extra in variants:
            case_name = f"{name}__stream_{str(stream).lower()}"
            payload = {
                "model": MODEL,
                "messages": [{"role": "user", "content": DEFAULT_PROMPT}],
                "stream": stream,
            }
            payload.update(extra)
            cases.append((case_name, payload))
    return cases


def redact_headers(headers):
    redacted = dict(headers)
    if "Authorization" in redacted:
        redacted["Authorization"] = "Bearer ***REDACTED***"
    return redacted


def save_text(path, text):
    path.write_text(text, encoding="utf-8")


def save_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_key_paths(obj, wanted, prefix="$"):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}"
            if key in wanted:
                found.append(path)
            found.extend(find_key_paths(value, wanted, path))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            found.extend(find_key_paths(value, wanted, f"{prefix}[{idx}]"))
    return found


def has_think_tags(text):
    return bool(re.search(r"<think>.*?</think>", text, flags=re.DOTALL | re.IGNORECASE))


def parse_sse_events(raw_text):
    events = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            events.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            continue
    return events


def collect_stream_delta_keys(events):
    keys = set()
    for event in events:
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            if isinstance(delta, dict):
                keys.update(delta.keys())
    return sorted(keys)


def extract_text_candidates(raw_text, parsed_json):
    texts = []
    if raw_text:
        texts.append(raw_text)
    if isinstance(parsed_json, dict):
        choices = parsed_json.get("choices") or []
        for choice in choices:
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(str(item["text"]))
                    elif isinstance(item, str):
                        texts.append(item)
            delta = choice.get("delta") or {}
            if isinstance(delta, dict):
                if isinstance(delta.get("content"), str):
                    texts.append(delta["content"])
    return "\n".join(part for part in texts if part)


def analyze_response(raw_text, parsed_json):
    key_paths = []
    stream_delta_keys = []
    if parsed_json is not None:
        key_paths = find_key_paths(parsed_json, set(SEARCH_KEYS))
    else:
        events = parse_sse_events(raw_text)
        key_paths = find_key_paths(events, set(SEARCH_KEYS))
        stream_delta_keys = collect_stream_delta_keys(events)
    combined_text = extract_text_candidates(raw_text, parsed_json)
    return {
        "json_parsed": parsed_json is not None,
        "found_key_paths": key_paths,
        "stream_delta_keys": stream_delta_keys,
        "has_think_tags": has_think_tags(combined_text),
        "combined_text_preview": combined_text[:500],
    }


def call_api(payload, api_key, url=API_URL, method="POST"):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with request.urlopen(http_request, timeout=180) as response:
            if isinstance(payload, dict) and payload.get("stream"):
                chunks = []
                while True:
                    line = response.readline()
                    if not line:
                        break
                    chunks.append(line)
                    if line.strip() == b"data: [DONE]":
                        break
                raw = b"".join(chunks)
            else:
                raw = response.read()
            return {
                "ok": True,
                "status": getattr(response, "status", 200),
                "headers": dict(response.headers.items()),
                "raw_bytes": raw,
            }
    except error.HTTPError as exc:
        raw = exc.read()
        return {
            "ok": False,
            "status": exc.code,
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "raw_bytes": raw,
        }
    except (TimeoutError, socket.timeout) as exc:
        return {
            "ok": False,
            "status": "timeout",
            "headers": {},
            "raw_bytes": str(exc).encode("utf-8", errors="replace"),
        }


def try_parse_json(raw_text):
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return None


def fetch_models_payload(api_key):
    result = call_api(None, api_key, url=MODELS_URL, method="GET")
    raw_text = result["raw_bytes"].decode("utf-8", errors="replace")
    return result, raw_text, try_parse_json(raw_text)


def render_markdown_report(meta, summary, models_payload):
    lines = [
        "# Reasoning Probe Report",
        "",
        f"- API URL: `{meta['api_url']}`",
        f"- Model: `{meta['model']}`",
        f"- Total cases: `{len(summary)}`",
        "",
        "## Model Metadata",
        "",
    ]

    models = []
    if isinstance(models_payload, dict):
        models = models_payload.get("data") or []

    if models:
        for model in models:
            if model.get("id") != meta["model"]:
                continue
            lines.append(f"- Model id: `{model.get('id', '')}`")
            if model.get("description"):
                lines.append(f"- Description: {model['description']}")
            if model.get("capabilities") is not None:
                lines.append(
                    f"- Capabilities: `{json.dumps(model['capabilities'], ensure_ascii=False, sort_keys=True)}`"
                )
            break
    else:
        lines.append("- No model metadata returned.")

    lines.extend(
        [
            "",
            "## Case Summary",
            "",
            "| Case | Status | JSON | Found Keys | Delta Keys | `<think>` |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )

    for item in summary:
        found_keys = ", ".join(item["found_key_paths"]) or "-"
        delta_keys = ", ".join(item.get("stream_delta_keys", [])) or "-"
        lines.append(
            f"| `{item['case']}` | `{item['status']}` | `{item['json_parsed']}` | {found_keys} | {delta_keys} | `{item['has_think_tags']}` |"
        )

    return "\n".join(lines) + "\n"


def main():
    api_key = os.environ.get("FIXMOST_API_KEY")
    if not api_key:
        raise SystemExit("FIXMOST_API_KEY is not set.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_dir = Path("probe_results") / f"reasoning_probe_{timestamp}"
    base_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    request_meta = {
        "api_url": API_URL,
        "models_url": MODELS_URL,
        "model": MODEL,
        "prompt": DEFAULT_PROMPT,
        "search_keys": list(SEARCH_KEYS),
    }
    save_json(base_dir / "meta.json", request_meta)

    models_result, models_raw_text, models_payload = fetch_models_payload(api_key)
    save_text(base_dir / "models_raw_response.txt", models_raw_text)
    save_json(
        base_dir / "models_response_meta.json",
        {
            "ok": models_result["ok"],
            "status": models_result["status"],
            "headers": redact_headers(models_result["headers"]),
        },
    )
    if models_payload is not None:
        save_json(base_dir / "models_parsed_response.json", models_payload)

    for case_name, payload in make_cases():
        case_dir = base_dir / case_name
        case_dir.mkdir(parents=True, exist_ok=True)

        save_json(case_dir / "request.json", payload)
        result = call_api(payload, api_key)

        raw_text = result["raw_bytes"].decode("utf-8", errors="replace")
        save_text(case_dir / "raw_response.txt", raw_text)
        save_json(case_dir / "response_meta.json", {
            "ok": result["ok"],
            "status": result["status"],
            "headers": redact_headers(result["headers"]),
        })

        parsed_json = try_parse_json(raw_text)
        if parsed_json is not None:
            save_json(case_dir / "parsed_response.json", parsed_json)

        analysis = analyze_response(raw_text, parsed_json)
        save_json(case_dir / "analysis.json", analysis)

        summary.append(
            {
                "case": case_name,
                "ok": result["ok"],
                "status": result["status"],
                "json_parsed": analysis["json_parsed"],
                "found_key_paths": analysis["found_key_paths"],
                "stream_delta_keys": analysis["stream_delta_keys"],
                "has_think_tags": analysis["has_think_tags"],
                "preview": analysis["combined_text_preview"],
            }
        )

    save_json(base_dir / "summary.json", summary)
    save_text(
        base_dir / "report.md",
        render_markdown_report(request_meta, summary, models_payload),
    )
    print(base_dir)


if __name__ == "__main__":
    main()

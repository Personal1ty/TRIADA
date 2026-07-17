import json


def extract_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("FixMost returned no choices.")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if content is None or content == "" or content == []:
        raise RuntimeError("FixMost returned empty content.")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)

        return "\n".join(parts)

    return str(content)


def extract_json_text(payload):
    text = extract_text(payload)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FixMost did not return valid JSON.") from exc
    return json.dumps(data, indent=2, sort_keys=True)

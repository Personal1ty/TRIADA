import json
import os
from urllib import error, request


API_URL = "https://api.llm.fixmost.com/v1/public/chat/completions"
MODEL = "corp-coder"
SYSTEM_PROMPT = (
    "You are a concise code analysis assistant. "
    "Never assume access to secrets. "
    "Never ask for secrets. "
    "Focus on structure, behavior, risk, and next checks."
)


def call_fixmost(prompt, system_prompt):
    api_key = os.environ.get("FIXMOST_API_KEY")
    if not api_key:
        raise RuntimeError("FIXMOST_API_KEY is not set.")

    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")

    http_request = request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(http_request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FixMost HTTP {exc.code}: {body[:1000]}") from exc

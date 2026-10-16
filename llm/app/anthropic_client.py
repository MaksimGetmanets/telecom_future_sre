"""Минимальный клиент Anthropic Messages API на httpx. Структурированный ответ через принудительный tool use."""
import time

import httpx

from .openai_client import LLMError
from .schema import RESPONSE_SCHEMA

TOOL = {
    "name": "diagnose",
    "description": "Записать диагноз инцидента и предложенное действие",
    "input_schema": RESPONSE_SCHEMA["schema"],
}


async def chat_json(http: httpx.AsyncClient, *, base_url: str, api_key: str, model: str,
                    messages: list[dict], timeout: float) -> tuple[dict, dict]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    body = {
        "model": model,
        "max_tokens": 800,
        "temperature": 0.1,
        "system": system,
        "messages": [m for m in messages if m["role"] != "system"],
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": TOOL["name"]},
    }
    t0 = time.monotonic()
    try:
        r = await http.post(f"{base_url}/v1/messages", json=body, timeout=timeout,
                            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    except httpx.HTTPError as exc:
        raise LLMError(f"сеть: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise LLMError(f"Anthropic вернул {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
        block = next(b for b in data["content"] if b.get("type") == "tool_use")
        parsed = block["input"]
        if not isinstance(parsed, dict):
            raise TypeError
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise LLMError("некорректный ответ модели") from exc
    usage = data.get("usage", {})
    tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
    meta = {"model": data.get("model", model), "latency_ms": int((time.monotonic() - t0) * 1000),
            "tokens": tokens or None}
    return parsed, meta

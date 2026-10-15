"""Минимальный клиент OpenAI Chat Completions на httpx (structured outputs)."""
import json
import time

import httpx

from .schema import RESPONSE_SCHEMA


class LLMError(Exception):
    pass


async def chat_json(http: httpx.AsyncClient, *, base_url: str, api_key: str, model: str,
                    messages: list[dict], timeout: float) -> tuple[dict, dict]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
    }
    t0 = time.monotonic()

    async def post(payload):
        try:
            return await http.post(f"{base_url}/chat/completions", json=payload, timeout=timeout,
                                   headers={"Authorization": f"Bearer {api_key}"})
        except httpx.HTTPError as exc:
            raise LLMError(f"сеть: {type(exc).__name__}") from exc

    r = await post(body)
    if r.status_code == 400:
        # шлюз или модель не поддерживает строгую схему: повторяем в режиме json_object
        # (формат ответа описан в системном промпте, проверку всё равно делает sanitize)
        body["response_format"] = {"type": "json_object"}
        r = await post(body)
    if r.status_code != 200:
        # тело ошибки не содержит ключа, но обрезаем на всякий случай
        raise LLMError(f"OpenAI вернул {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("некорректный ответ модели") from exc
    usage = data.get("usage", {})
    meta = {"model": data.get("model", model), "latency_ms": int((time.monotonic() - t0) * 1000),
            "tokens": usage.get("total_tokens")}
    return parsed, meta

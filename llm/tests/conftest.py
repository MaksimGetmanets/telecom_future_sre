import json
import pathlib
import sys

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.assistant import Assistant  # noqa: E402
from app.config import Settings  # noqa: E402

PROMPTS = str(pathlib.Path(__file__).resolve().parent.parent / "prompts")

KUBE = {
    "deployments": {"orders": {"replicas": 2, "ready": 2, "image": "x:1"}, "gateway": {"replicas": 2, "ready": 2, "image": "y:1"}},
    "pods": [{"name": "orders-1", "phase": "Running", "restarts": 0}],
    "events": ["Warning Unhealthy: probe failed"],
}


def make_transport(llm_answer=None, llm_status=200, calls=None, strict_schema_unsupported=False):
    calls = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "/api/v1/query" in url:
            return httpx.Response(200, json={"data": {"result": [{"value": [0, "0.48"]}]}})
        if "query_range" in url:
            return httpx.Response(200, json={"data": {"result": [{"values": [["1", "ERROR injected fault password=hunter2"], ["2", "ERROR injected fault password=hunter2"]]}]}})
        if "chat/completions" in url:
            if llm_status != 200:
                return httpx.Response(llm_status, text="boom")
            body = json.loads(request.content)
            calls.append(body)
            if strict_schema_unsupported and body["response_format"]["type"] == "json_schema":
                return httpx.Response(400, text="response_format unsupported")
            return httpx.Response(200, json={"model": "gpt-test", "usage": {"total_tokens": 321},
                                             "choices": [{"message": {"content": json.dumps(llm_answer)}}]})
        if url.endswith("/v1/messages"):
            if llm_status != 200:
                return httpx.Response(llm_status, text="boom")
            body = json.loads(request.content)
            body["_headers"] = {"x-api-key": request.headers.get("x-api-key"), "version": request.headers.get("anthropic-version")}
            calls.append(body)
            return httpx.Response(200, json={"model": "claude-test", "usage": {"input_tokens": 300, "output_tokens": 40},
                                             "content": [{"type": "text", "text": "..."}, {"type": "tool_use", "name": "diagnose", "input": llm_answer}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def settings():
    return Settings(openai_api_key="sk-test-1234567890abcdef", mock=False, prompts_dir=PROMPTS)


@pytest.fixture
def alert():
    return {"fingerprint": "abc", "labels": {"alertname": "DemoHighErrorRate", "namespace": "demo", "deployment": "orders", "severity": "critical"},
            "annotations": {"summary": "5xx > 5%"}}


def build(settings, transport, kube=True, clock=None):
    http = httpx.AsyncClient(transport=transport)
    kube_fn = (lambda ns, dep: KUBE) if kube else None
    kwargs = {"clock": clock} if clock else {}
    return Assistant(settings, http, kube_fn, **kwargs)


GOOD = {"hypothesis": "ошибка приложения", "confidence": 0.8, "evidence": ["error_ratio_5m=0.48"],
        "action": "restart", "deployment": "orders", "replicas": 0}

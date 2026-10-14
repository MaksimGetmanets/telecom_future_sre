import json
from concurrent.futures import Future

import httpx

from app import audit
from app.assistant import Assistant
from app.engine import Engine
from app.guard import Guard
from test_remediator import Clock, FakeKube, alert, payload, policies  # noqa: F401


class Inline:
    """Исполнитель, который выполняет задачу сразу (в тестах не нужны потоки)."""
    def submit(self, fn, *a):
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:
            f.set_exception(exc)
        return f


def llm(answer=None, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append((request.headers.get("authorization"), json.loads(request.content)))
        if status != 200:
            return httpx.Response(status, text="x")
        return httpx.Response(200, json=answer)
    return httpx.Client(transport=httpx.MockTransport(handler))


ANSWER = {"hypothesis": "ошибка приложения", "confidence": 0.8, "evidence": ["e1"], "validated": True,
          "suggested_action": {"type": "restart", "deployment": "orders"}, "model": "gpt-test", "latency_ms": 900, "cached": False}


def engine(policies, assistant, dry_run=False):
    return Engine(policies, FakeKube(), dry_run, Guard(180, 6, Clock()), assistant=assistant)


def last(event):
    return next(e for e in audit.recent(20) if e["event"] == event)


def test_diagnosis_written_to_audit_and_agrees(policies):
    seen = []
    a = Assistant("http://llm/diagnose", token="t", client=llm(ANSWER, seen=seen), executor=Inline())
    [r] = engine(policies, a).handle(payload(alert()))
    assert r["status"] == "executed"
    d = last("llm_diagnosis")
    assert d["agrees"] is True and d["policy_action"] == "restart" and d["model"] == "gpt-test"
    assert seen[0][0] == "Bearer t" and seen[0][1]["labels"]["deployment"] == "orders"


def test_disagreement_is_flagged(policies):
    ans = {**ANSWER, "suggested_action": {"type": "scale", "deployment": "orders", "replicas": 3}}
    a = Assistant("http://llm/diagnose", client=llm(ans), executor=Inline())
    engine(policies, a).handle(payload(alert()))
    assert last("llm_diagnosis")["agrees"] is False


def test_assistant_failure_does_not_break_remediation(policies):
    a = Assistant("http://llm/diagnose", client=llm(status=500), executor=Inline())
    [r] = engine(policies, a).handle(payload(alert()))
    assert r["status"] == "executed"
    d = last("llm_diagnosis")
    assert d["status"] == "unavailable"


def test_assistant_called_only_for_real_decisions(policies):
    seen = []
    a = Assistant("http://llm/diagnose", client=llm(ANSWER, seen=seen), executor=Inline())
    engine(policies, a).handle(payload(alert(status="resolved"), alert(name="Unknown")))
    assert seen == []


def test_submit_error_is_swallowed(policies):
    class Broken:
        def submit(self, *a):
            raise RuntimeError("pool closed")
    a = Assistant("http://llm/diagnose", client=llm(ANSWER), executor=Broken())
    [r] = engine(policies, a).handle(payload(alert()))
    assert r["status"] == "executed"

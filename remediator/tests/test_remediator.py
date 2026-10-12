import pathlib

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import Engine
from app.guard import Guard
from app.main import create_app
from app.policies import load, parse

POLICY_FILE = pathlib.Path(__file__).resolve().parent.parent / "policies.yaml"


class FakeKube:
    def __init__(self, replicas=2):
        self.replicas = replicas
        self.calls = []

    def restart(self, ns, dep):
        self.calls.append(("restart", ns, dep))

    def get_replicas(self, ns, dep):
        return self.replicas

    def set_replicas(self, ns, dep, n):
        self.calls.append(("scale", ns, dep, n))
        self.replicas = n


def alert(name="DemoHighErrorRate", ns="demo", dep="orders", status="firing"):
    labels = {"alertname": name, "severity": "page"}
    if ns:
        labels["namespace"] = ns
    if dep:
        labels["deployment"] = dep
    return {"status": status, "labels": labels, "annotations": {"runbook_url": "docs/runbooks/x.md"}}


def payload(*alerts):
    return {"version": "4", "status": "firing", "alerts": list(alerts)}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def policies():
    return load(str(POLICY_FILE))


def make(policies, dry_run=False, replicas=2, clock=None):
    kube = FakeKube(replicas)
    guard = Guard(policies.defaults.cooldown_seconds, policies.defaults.max_actions_per_hour, clock or Clock())
    return Engine(policies, kube, dry_run, guard), kube


def test_restart_executes(policies):
    engine, kube = make(policies)
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "executed" and r["action"] == "restart"
    assert kube.calls == [("restart", "demo", "orders")]


def test_dry_run_changes_nothing(policies):
    engine, kube = make(policies, dry_run=True)
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "dry_run"
    assert kube.calls == []


def test_scale_up_by_step_and_cap(policies):
    engine, kube = make(policies, replicas=3, clock=Clock())
    [r] = engine.handle(payload(alert("DemoHighLatency", dep="gateway")))
    assert r["status"] == "executed" and (r["replicas_from"], r["replicas_to"]) == (3, 4)
    clock = Clock()
    engine2, kube2 = make(policies, replicas=4, clock=clock)
    [r2] = engine2.handle(payload(alert("DemoHighLatency")))
    assert r2["status"] == "skipped_at_max" and kube2.calls == []


def test_resolved_alert_ignored(policies):
    engine, kube = make(policies)
    [r] = engine.handle(payload(alert(status="resolved")))
    assert r["status"] == "skipped_not_firing" and kube.calls == []


def test_unknown_alert_no_policy(policies):
    engine, kube = make(policies)
    [r] = engine.handle(payload(alert("SomethingElse")))
    assert r["status"] == "skipped_no_policy" and kube.calls == []


def test_missing_target_labels(policies):
    engine, kube = make(policies)
    [r] = engine.handle(payload(alert(dep=None)))
    assert r["status"] == "skipped_no_target" and kube.calls == []


def test_foreign_namespace_untouched(policies):
    engine, kube = make(policies)
    [r] = engine.handle(payload(alert(ns="kube-system", dep="coredns")))
    assert r["status"] == "skipped_namespace" and kube.calls == []


def test_cooldown_then_allowed_again(policies):
    clock = Clock()
    engine, kube = make(policies, clock=clock)
    engine.handle(payload(alert()))
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "skipped_guard" and "cooldown" in r["detail"]
    clock.t += policies.defaults.cooldown_seconds + 1
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "executed"
    assert len(kube.calls) == 2


def test_hourly_limit(policies):
    clock = Clock()
    engine, kube = make(policies, clock=clock)
    for _ in range(policies.defaults.max_actions_per_hour):
        engine.handle(payload(alert()))
        clock.t += policies.defaults.cooldown_seconds + 1
    # 6 действий * 181 c = ~18 минут, лимит ещё не отпустил
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "skipped_guard" and "rate_limit" in r["detail"]
    clock.t += 3600
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "executed"


def test_kube_error_is_reported_not_raised(policies):
    engine, kube = make(policies)

    def boom(ns, dep):
        raise RuntimeError("forbidden")

    kube.restart = boom
    [r] = engine.handle(payload(alert()))
    assert r["status"] == "error" and "forbidden" in r["detail"]


def test_batch_of_alerts(policies):
    engine, kube = make(policies)
    results = engine.handle(payload(alert(dep="orders"), alert("DemoHighLatency", dep="gateway")))
    assert [r["status"] for r in results] == ["executed", "executed"]


def test_policy_validation():
    with pytest.raises(ValueError):
        parse({"policies": [{"match": {"alertname": "x"}, "action": "format-disk"}]})
    with pytest.raises(ValueError):
        parse({"policies": [{"match": {}, "action": "restart"}]})


def test_notify_called_for_actions_only(policies):
    sent = []
    kube = FakeKube()
    engine = Engine(policies, kube, False, Guard(180, 6, Clock()), notify=sent.append)
    engine.handle(payload(alert(), alert("SomethingElse")))
    assert [r["status"] for r in sent] == ["executed"]


def client(policies, token="", dry_run=False):
    app = create_app(Settings(dry_run=dry_run, webhook_token=token), kube=FakeKube(), policies=policies)
    return TestClient(app)


def test_http_alert_and_audit(policies):
    c = client(policies)
    resp = c.post("/alert", json=payload(alert()))
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "executed"
    assert c.get("/audit").json()[0]["alertname"] == "DemoHighErrorRate"
    assert "remediator_actions_total" in c.get("/metrics").text
    assert c.get("/healthz").json()["status"] == "ok"


def test_http_token(policies):
    c = client(policies, token="s3cret")
    assert c.post("/alert", json=payload(alert())).status_code == 401
    assert c.post("/alert", json=payload(alert()), headers={"Authorization": "Bearer s3cret"}).status_code == 200

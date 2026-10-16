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
    def __init__(self, replicas=2, rollback_detail="ревизия 3 -> шаблон ревизии 2"):
        self.replicas = replicas
        self.calls = []
        self.rollback_detail = rollback_detail  # None = откатываться некуда

    def rollback(self, ns, dep, dry_run=False):
        if self.rollback_detail is not None and not dry_run:
            self.calls.append(("rollback", ns, dep))
        return self.rollback_detail

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


def make(policies, dry_run=False, replicas=2, clock=None, rollback_detail="ревизия 3 -> шаблон ревизии 2"):
    kube = FakeKube(replicas, rollback_detail)
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
    [r] = engine.handle(payload(alert("OrdersLatencyBurn", dep="orders")))
    assert r["status"] == "executed" and (r["replicas_from"], r["replicas_to"]) == (3, 4)
    clock = Clock()
    engine2, kube2 = make(policies, replicas=4, clock=clock)
    [r2] = engine2.handle(payload(alert("OrdersLatencyBurn")))
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
    results = engine.handle(payload(alert(dep="orders"), alert("OrdersLatencyBurn", dep="orders")))
    assert [r["status"] for r in results] == ["executed", "executed"]


def test_policy_validation():
    with pytest.raises(ValueError):
        parse({"policies": [{"match": {"alertname": "x"}, "action": "format-disk"}]})
    with pytest.raises(ValueError):
        parse({"policies": [{"match": {}, "action": "restart"}]})
    # rollback теперь допустимое действие политики
    assert parse({"policies": [{"match": {"alertname": "x"}, "action": "rollback"}]}).policies[0].action == "rollback"


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


def test_sloth_alert_names_map_to_actions(policies):
    # имена алертов из observability/slo (Sloth) должны попадать в политики
    engine, kube = make(policies)
    results = engine.handle(payload(
        alert("OrdersAvailabilityBurn", dep="orders"),
        alert("OrdersLatencyBurn", dep="orders"),
        alert("GatewayLatencyBurn", dep="gateway"),
        alert("GatewayAvailabilityBurn", dep="gateway"),
    ))
    assert [(r["action"], r["status"]) for r in results] == [
        ("restart", "executed"),
        ("scale", "executed"),
        (None, "skipped_no_policy"),
        ("restart", "executed"),
    ]


def test_demo_high_latency_restarts_instead_of_scaling(policies):
    """Сбой задержки из chaos/fault.sh живёт в поде: scale его не лечит, поэтому DemoHighLatency идёт в restart."""
    engine, kube = make(policies)
    [r] = engine.handle(payload(alert("DemoHighLatency", dep="orders")))
    assert r["status"] == "executed" and kube.calls[0][0] == "restart"


# --- подтверждённые человеком действия (кнопка в Telegram) ---

def test_manual_restart_executes_and_is_audited(policies):
    engine, kube = make(policies)
    r = engine.execute_manual("restart", "demo", "orders")
    assert r["status"] == "executed" and kube.calls == [("restart", "demo", "orders")]
    assert r["policy"] == "manual-confirm"


def test_manual_scale_to_requested_replicas(policies):
    engine, kube = make(policies, replicas=2)
    r = engine.execute_manual("scale", "demo", "orders", 3)
    assert r["status"] == "executed" and (r["replicas_from"], r["replicas_to"]) == (2, 3)
    assert kube.calls == [("scale", "demo", "orders", 3)]


def test_manual_scale_without_replicas_adds_one(policies):
    engine, kube = make(policies, replicas=2)
    r = engine.execute_manual("scale", "demo", "orders")
    assert r["replicas_to"] == 3


def test_manual_scale_above_max_rejected(policies):
    engine, kube = make(policies, replicas=2)
    r = engine.execute_manual("scale", "demo", "orders", 99)
    assert r["status"] == "rejected" and kube.calls == []


def test_manual_rejects_unknown_action_and_foreign_namespace(policies):
    engine, kube = make(policies)
    assert engine.execute_manual("delete", "demo", "orders")["status"] == "rejected"
    assert engine.execute_manual("restart", "kube-system", "coredns")["status"] == "skipped_namespace"
    assert kube.calls == []


def test_manual_respects_cooldown_and_dry_run(policies):
    engine, kube = make(policies)
    engine.execute_manual("restart", "demo", "orders")
    r = engine.execute_manual("restart", "demo", "orders")
    assert r["status"] == "skipped_guard" and len(kube.calls) == 1
    engine2, kube2 = make(policies, dry_run=True)
    assert engine2.execute_manual("restart", "demo", "orders")["status"] == "dry_run" and kube2.calls == []


def test_manual_kube_error_reported(policies):
    engine, kube = make(policies)

    def boom(ns, dep):
        raise RuntimeError("forbidden")

    kube.restart = boom
    r = engine.execute_manual("restart", "demo", "orders")
    assert r["status"] == "error" and "forbidden" in r["detail"]


def test_http_execute_requires_token_and_validates(policies):
    c = client(policies, token="s3cret")
    body = {"action": "restart", "namespace": "demo", "deployment": "orders"}
    assert c.post("/execute", json=body).status_code == 401
    h = {"Authorization": "Bearer s3cret"}
    assert c.post("/execute", json={"action": "restart"}, headers=h).status_code == 422
    assert c.post("/execute", json={**body, "replicas": "3"}, headers=h).status_code == 422
    resp = c.post("/execute", json=body, headers=h)
    assert resp.status_code == 200 and resp.json()["status"] == "executed"
    assert any(e["event"] == "manual_remediation" for e in c.get("/audit", headers=h).json())


# --- откат (rollback) ---

ROLLBACK_POLICY = {"policies": [{"name": "rb", "match": {"alertname": "DemoBadRelease"}, "action": "rollback"}]}


def test_rollback_policy_executes():
    engine, kube = make(parse(ROLLBACK_POLICY))
    [r] = engine.handle(payload(alert("DemoBadRelease", dep="orders")))
    assert r["status"] == "executed" and r["action"] == "rollback"
    assert "ревизия 3 -> шаблон ревизии 2" in r["detail"]
    assert kube.calls == [("rollback", "demo", "orders")]


def test_rollback_dry_run_changes_nothing():
    engine, kube = make(parse(ROLLBACK_POLICY), dry_run=True)
    [r] = engine.handle(payload(alert("DemoBadRelease", dep="orders")))
    assert r["status"] == "dry_run" and kube.calls == []


def test_rollback_without_previous_revision_is_skipped():
    engine, kube = make(parse(ROLLBACK_POLICY), rollback_detail=None)
    [r] = engine.handle(payload(alert("DemoBadRelease", dep="orders")))
    assert r["status"] == "skipped_no_previous" and kube.calls == []


def test_manual_rollback_executes_and_respects_guard(policies):
    engine, kube = make(policies)
    r = engine.execute_manual("rollback", "demo", "orders")
    assert r["status"] == "executed" and r["action"] == "rollback" and "по подтверждению" in r["detail"]
    assert kube.calls == [("rollback", "demo", "orders")]
    assert engine.execute_manual("rollback", "demo", "orders")["status"] == "skipped_guard"
    assert engine.execute_manual("rollback", "kube-system", "coredns")["status"] == "skipped_namespace"


def test_manual_rollback_dry_run_and_nowhere_to_go(policies):
    engine, kube = make(policies, dry_run=True)
    assert engine.execute_manual("rollback", "demo", "orders")["status"] == "dry_run" and kube.calls == []
    engine2, _ = make(policies, rollback_detail=None)
    assert engine2.execute_manual("rollback", "demo", "orders")["status"] == "skipped_no_previous"


def test_http_execute_rollback(policies):
    c = client(policies)
    resp = c.post("/execute", json={"action": "rollback", "namespace": "demo", "deployment": "orders"})
    assert resp.status_code == 200 and resp.json()["status"] == "executed" and resp.json()["action"] == "rollback"


# --- выбор ревизии для отката ---

from app.kube import pick_rollback_target  # noqa: E402


def tpl(image, restarted_at=None, hash_="abc"):
    meta = {"labels": {"app": "orders", "pod-template-hash": hash_}}
    if restarted_at:
        meta["annotations"] = {"kubectl.kubernetes.io/restartedAt": restarted_at}
    return {"metadata": meta, "spec": {"containers": [{"name": "orders", "image": image}]}}


def test_pick_previous_revision_with_other_image():
    revs = [{"revision": 1, "template": tpl("orders:1")}, {"revision": 2, "template": tpl("orders:2")}]
    assert pick_rollback_target(revs, 2, tpl("orders:2", hash_="zzz"))["revision"] == 1


def test_pick_skips_restart_only_revisions():
    """rollout restart создаёт новую ревизию с тем же образом: откат на неё ничего бы не изменил."""
    revs = [
        {"revision": 1, "template": tpl("orders:1")},
        {"revision": 2, "template": tpl("orders:2")},
        {"revision": 3, "template": tpl("orders:2", "2026-10-15T20:00:00")},
        {"revision": 4, "template": tpl("orders:2", "2026-10-15T20:05:00")},
    ]
    assert pick_rollback_target(revs, 4, revs[3]["template"])["revision"] == 1


def test_pick_returns_none_when_nowhere_to_go():
    assert pick_rollback_target([{"revision": 1, "template": tpl("orders:1")}], 1, tpl("orders:1")) is None
    revs = [{"revision": 1, "template": tpl("orders:1")}, {"revision": 2, "template": tpl("orders:1", "t")}]
    assert pick_rollback_target(revs, 2, revs[1]["template"]) is None


# --- RealKube.rollback на поддельном API (без кластера) ---

def _models():
    from kubernetes import client as k

    def template(image, hash_=None, restarted=None):
        labels = {"app": "orders"}
        if hash_:
            labels["pod-template-hash"] = hash_
        ann = {"kubectl.kubernetes.io/restartedAt": restarted} if restarted else None
        return k.V1PodTemplateSpec(
            metadata=k.V1ObjectMeta(labels=labels, annotations=ann),
            spec=k.V1PodSpec(containers=[k.V1Container(name="orders", image=image)]),
        )

    def rs(name, revision, image, restarted=None, owner="orders"):
        return k.V1ReplicaSet(
            metadata=k.V1ObjectMeta(
                name=name, annotations={"deployment.kubernetes.io/revision": str(revision)},
                owner_references=[k.V1OwnerReference(api_version="apps/v1", kind="Deployment", name=owner, uid="u")],
            ),
            spec=k.V1ReplicaSetSpec(selector=k.V1LabelSelector(match_labels={"app": "orders"}),
                                    template=template(image, "h" + str(revision), restarted)),
        )

    dep = k.V1Deployment(
        metadata=k.V1ObjectMeta(name="orders", annotations={"deployment.kubernetes.io/revision": "3"}),
        spec=k.V1DeploymentSpec(selector=k.V1LabelSelector(match_labels={"app": "orders"}),
                                template=template("orders:2", None, "2026-10-15T20:00:00")),
    )
    items = [rs("a", 1, "orders:1"), rs("b", 2, "orders:2"), rs("c", 3, "orders:2", "2026-10-15T20:00:00"),
             rs("other", 9, "evil:1", owner="gateway")]
    return k, dep, items


class FakeApps:
    def __init__(self, dep, items):
        self.dep, self.items, self.patches = dep, items, []

    def read_namespaced_deployment(self, name, ns):
        return self.dep

    def list_namespaced_replica_set(self, ns, label_selector=""):
        assert label_selector == "app=orders"
        from types import SimpleNamespace
        return SimpleNamespace(items=self.items)

    def patch_namespaced_deployment(self, name, ns, body, _content_type=None):
        self.patches.append((name, ns, body, _content_type))


def test_realkube_rollback_patches_previous_template():
    from app.kube import RealKube

    _, dep, items = _models()
    kube = RealKube()
    kube._apps = FakeApps(dep, items)
    detail = kube.rollback("demo", "orders")
    assert detail == "ревизия 3 -> шаблон ревизии 1"      # ревизия 2 (orders:2) совпадает с текущей по образу, поэтому пропускается
    [(name, ns, body, ctype)] = kube._apps.patches
    assert (name, ns, ctype) == ("orders", "demo", "application/json-patch+json")
    [op] = body
    assert op["op"] == "replace" and op["path"] == "/spec/template"
    assert op["value"]["spec"]["containers"][0]["image"] == "orders:1"
    assert "pod-template-hash" not in op["value"]["metadata"]["labels"]


def test_realkube_rollback_dry_run_and_nowhere_to_go():
    from app.kube import RealKube

    k, dep, items = _models()
    kube = RealKube()
    kube._apps = FakeApps(dep, items)
    assert kube.rollback("demo", "orders", dry_run=True) == "ревизия 3 -> шаблон ревизии 1"
    assert kube._apps.patches == []
    kube2 = RealKube()
    kube2._apps = FakeApps(dep, [items[2]])   # осталась только текущая ревизия
    assert kube2.rollback("demo", "orders") is None and kube2._apps.patches == []

"""Ядро: из алертов Alertmanager получаем решения и выполняем действия."""
from typing import Callable

from . import audit
from .guard import Guard
from .kube import Kube
from .policies import Policy, PolicySet

NOTIFY_STATUSES = {"executed", "dry_run", "error"}


class Engine:
    def __init__(self, policies: PolicySet, kube: Kube, dry_run: bool, guard: Guard | None = None,
                 notify: Callable[[dict], None] | None = None):
        self.policies = policies
        self.kube = kube
        self.dry_run = dry_run
        self.guard = guard or Guard(policies.defaults.cooldown_seconds, policies.defaults.max_actions_per_hour)
        self.notify = notify

    def handle(self, payload: dict) -> list[dict]:
        results = []
        for alert in payload.get("alerts", []):
            result = self._handle_alert(alert)
            results.append(result)
            audit.record(**result)
            if self.notify and result["status"] in NOTIFY_STATUSES:
                self.notify(result)
        return results

    def _handle_alert(self, alert: dict) -> dict:
        labels = alert.get("labels") or {}
        base = {
            "alertname": labels.get("alertname", ""),
            "namespace": labels.get("namespace"),
            "deployment": labels.get("deployment"),
            "action": None,
            "dry_run": self.dry_run,
            "runbook_url": (alert.get("annotations") or {}).get("runbook_url"),
        }

        def done(status: str, detail: str = "", **extra) -> dict:
            return {**base, **extra, "status": status, "detail": detail}

        if alert.get("status") != "firing":
            return done("skipped_not_firing")
        policy = self.policies.find(labels)
        if policy is None:
            return done("skipped_no_policy")
        base["action"] = policy.action
        base["policy"] = policy.name
        ns, dep = base["namespace"], base["deployment"]
        if not ns or not dep:
            return done("skipped_no_target", "в алерте нет лейблов namespace/deployment")
        if ns not in self.policies.defaults.allowed_namespaces:
            return done("skipped_namespace", f"namespace {ns} не входит в allowed_namespaces")
        reason = self.guard.check_and_record(ns, dep, policy.action)
        if reason:
            return done("skipped_guard", reason)
        try:
            return self._execute(policy, ns, dep, done)
        except Exception as exc:
            return done("error", f"{type(exc).__name__}: {exc}")

    def _execute(self, policy: Policy, ns: str, dep: str, done) -> dict:
        if policy.action == "restart":
            if not self.dry_run:
                self.kube.restart(ns, dep)
            return done("dry_run" if self.dry_run else "executed", "rollout restart")
        # scale
        step = int(policy.params.get("step", 1))
        maximum = int(policy.params.get("max", 4))
        current = self.kube.get_replicas(ns, dep)
        target = min(current + step, maximum)
        if target <= current:
            return done("skipped_at_max", f"уже {current} реплик, максимум {maximum}", replicas_from=current, replicas_to=current)
        if not self.dry_run:
            self.kube.set_replicas(ns, dep, target)
        return done("dry_run" if self.dry_run else "executed", f"replicas {current} -> {target}",
                    replicas_from=current, replicas_to=target)

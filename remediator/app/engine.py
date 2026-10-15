"""Ядро: из алертов Alertmanager получаем решения и выполняем действия."""
from typing import Callable

from . import audit
from .guard import Guard
from .kube import Kube
from .policies import Policy, PolicySet

NOTIFY_STATUSES = {"executed", "dry_run", "error"}
MANUAL_ACTIONS = ("restart", "scale", "rollback")


class Engine:
    def __init__(self, policies: PolicySet, kube: Kube, dry_run: bool, guard: Guard | None = None,
                 notify: Callable[[dict], None] | None = None, assistant=None):
        self.policies = policies
        self.kube = kube
        self.dry_run = dry_run
        self.guard = guard or Guard(policies.defaults.cooldown_seconds, policies.defaults.max_actions_per_hour)
        self.notify = notify
        self.assistant = assistant

    def handle(self, payload: dict) -> list[dict]:
        results = []
        for alert in payload.get("alerts", []):
            result = self._handle_alert(alert)
            results.append(result)
            audit.record(**result)
            if self.notify and result["status"] in NOTIFY_STATUSES:
                self.notify(result)
            if self.assistant and result["status"] in NOTIFY_STATUSES:
                self.assistant.advise(alert, result)
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
        if policy.action == "rollback":
            return self._rollback(ns, dep, done)
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

    def _rollback(self, ns: str, dep: str, done, suffix: str = "") -> dict:
        detail = self.kube.rollback(ns, dep, dry_run=self.dry_run)
        if detail is None:
            return done("skipped_no_previous", "нет предыдущей ревизии с другим шаблоном пода: откатываться некуда")
        return done("dry_run" if self.dry_run else "executed", f"rollback: {detail}{suffix}")

    def execute_manual(self, action: str, namespace: str, deployment: str, replicas: int | None = None,
                       source: str = "telegram") -> dict:
        """Действие, подтверждённое человеком (кнопка в Telegram). Те же ограничения, что у автоматики:
        белый список namespace и действий, пауза и часовой лимит, dry-run. Пишется в аудит как manual_remediation."""
        base = {
            "alertname": "manual", "namespace": namespace, "deployment": deployment,
            "action": action if action in MANUAL_ACTIONS else None, "dry_run": self.dry_run,
            "policy": "manual-confirm", "source": source, "runbook_url": None,
        }

        def done(status: str, detail: str = "", **extra) -> dict:
            result = {**base, **extra, "status": status, "detail": detail}
            audit.record(**{**result, "event": "manual_remediation"})
            return result

        if action not in MANUAL_ACTIONS:
            return done("rejected", f"действие {action!r} не из белого списка {MANUAL_ACTIONS}")
        if not namespace or not deployment:
            return done("rejected", "не указан namespace или deployment")
        if namespace not in self.policies.defaults.allowed_namespaces:
            return done("skipped_namespace", f"namespace {namespace} не входит в allowed_namespaces")
        maximum = max((int(p.params.get("max", 4)) for p in self.policies.policies if p.action == "scale"), default=4)
        if action == "scale" and replicas is not None and not 1 <= replicas <= maximum:
            return done("rejected", f"реплик должно быть от 1 до {maximum}, получено {replicas}")
        reason = self.guard.check_and_record(namespace, deployment, action)
        if reason:
            return done("skipped_guard", reason)
        try:
            if action == "restart":
                if not self.dry_run:
                    self.kube.restart(namespace, deployment)
                return done("dry_run" if self.dry_run else "executed", "rollout restart (по подтверждению)")
            if action == "rollback":
                return self._rollback(namespace, deployment, done, " (по подтверждению)")
            current = self.kube.get_replicas(namespace, deployment)
            target = replicas if replicas is not None else min(current + 1, maximum)
            if target == current:
                return done("skipped_at_max", f"уже {current} реплик", replicas_from=current, replicas_to=current)
            if not self.dry_run:
                self.kube.set_replicas(namespace, deployment, target)
            return done("dry_run" if self.dry_run else "executed", f"replicas {current} -> {target} (по подтверждению)",
                        replicas_from=current, replicas_to=target)
        except Exception as exc:
            return done("error", f"{type(exc).__name__}: {exc}")

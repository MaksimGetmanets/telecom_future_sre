"""Работа с Kubernetes. Интерфейс узкий, чтобы в тестах подставлять заглушку."""
import copy
from datetime import datetime, timezone
from typing import Protocol


class Kube(Protocol):
    def restart(self, namespace: str, deployment: str) -> None: ...
    def rollback(self, namespace: str, deployment: str, dry_run: bool = False) -> str | None: ...
    def get_replicas(self, namespace: str, deployment: str) -> int: ...
    def set_replicas(self, namespace: str, deployment: str, replicas: int) -> None: ...


_STRATEGIC = "application/strategic-merge-patch+json"
_JSON_PATCH = "application/json-patch+json"
_REVISION = "deployment.kubernetes.io/revision"
_RESTARTED_AT = "kubectl.kubernetes.io/restartedAt"


def _normalized(template: dict) -> dict:
    """Шаблон пода без служебных полей (pod-template-hash, метка перезапуска): по нему сравниваем ревизии."""
    t = copy.deepcopy(template or {})
    meta = t.get("metadata") or {}
    (meta.get("labels") or {}).pop("pod-template-hash", None)
    (meta.get("annotations") or {}).pop(_RESTARTED_AT, None)
    for key in ("labels", "annotations"):
        if key in meta and not meta[key]:
            del meta[key]
    t["metadata"] = meta
    return t


def pick_rollback_target(revisions: list[dict], current_revision: int, current_template: dict) -> dict | None:
    """Выбор ревизии для отката, как у `kubectl rollout undo`, но умнее: ревизии, которые отличаются от текущей
    только меткой перезапуска (их создаёт сам `rollout restart`), пропускаем, иначе откат ничего бы не менял.

    revisions: [{"revision": int, "template": dict}]. Возвращает самую свежую ревизию старше текущей с другим шаблоном."""
    current = _normalized(current_template)
    older = sorted((r for r in revisions if r["revision"] < current_revision), key=lambda r: r["revision"], reverse=True)
    for rev in older:
        if _normalized(rev["template"]) != current:
            return rev
    return None


class RealKube:
    def __init__(self):
        self._apps = None

    def _api(self):
        if self._apps is None:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._apps = client.AppsV1Api()
        return self._apps

    def restart(self, namespace: str, deployment: str) -> None:
        # то же, что делает `kubectl rollout restart`: меняем аннотацию шаблона пода
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")
                        }
                    }
                }
            }
        }
        self._api().patch_namespaced_deployment(deployment, namespace, body, _content_type=_STRATEGIC)

    def get_replicas(self, namespace: str, deployment: str) -> int:
        return int(self._api().read_namespaced_deployment_scale(deployment, namespace).spec.replicas or 0)

    def set_replicas(self, namespace: str, deployment: str, replicas: int) -> None:
        self._api().patch_namespaced_deployment_scale(
            deployment, namespace, {"spec": {"replicas": replicas}}, _content_type=_STRATEGIC
        )

    def rollback(self, namespace: str, deployment: str, dry_run: bool = False) -> str | None:
        """Откат на предыдущую ревизию (как `kubectl rollout undo`). None, если откатываться некуда.
        При dry_run только проверяет, что откат возможен, и ничего не меняет."""
        from kubernetes import client

        api = self._api()
        dep = api.read_namespaced_deployment(deployment, namespace)
        current_revision = int((dep.metadata.annotations or {}).get(_REVISION, "0"))
        selector = ",".join(f"{k}={v}" for k, v in (dep.spec.selector.match_labels or {}).items())
        serialize = client.ApiClient().sanitize_for_serialization
        revisions = []
        for rs in api.list_namespaced_replica_set(namespace, label_selector=selector).items:
            owned = any(o.kind == "Deployment" and o.name == deployment for o in (rs.metadata.owner_references or []))
            if owned:
                revisions.append({"revision": int((rs.metadata.annotations or {}).get(_REVISION, "0")),
                                  "template": serialize(rs.spec.template)})
        target = pick_rollback_target(revisions, current_revision, serialize(dep.spec.template))
        if target is None:
            return None
        if not dry_run:
            template = copy.deepcopy(target["template"])
            ((template.get("metadata") or {}).get("labels") or {}).pop("pod-template-hash", None)
            api.patch_namespaced_deployment(
                deployment, namespace, [{"op": "replace", "path": "/spec/template", "value": template}],
                _content_type=_JSON_PATCH,
            )
        return f"ревизия {current_revision} -> шаблон ревизии {target['revision']}"

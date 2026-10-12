"""Работа с Kubernetes. Интерфейс узкий, чтобы в тестах подставлять заглушку."""
from datetime import datetime, timezone
from typing import Protocol


class Kube(Protocol):
    def restart(self, namespace: str, deployment: str) -> None: ...
    def get_replicas(self, namespace: str, deployment: str) -> int: ...
    def set_replicas(self, namespace: str, deployment: str, replicas: int) -> None: ...


_STRATEGIC = "application/strategic-merge-patch+json"


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

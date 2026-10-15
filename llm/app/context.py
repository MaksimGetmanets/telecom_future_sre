"""Сбор контекста инцидента: метрики Prometheus, логи Loki, состояние Kubernetes."""
import asyncio
import logging
import time
from string import Template

import httpx

from .redact import redact

log = logging.getLogger("llm.context")

# $d подставляется именем deployment; метрики из Spring Boot (Micrometer) и kube-state-metrics
QUERIES = {
    "error_ratio_5m": '(sum(rate(http_server_requests_seconds_count{application="$d",status=~"5.."}[5m])) or vector(0)) / clamp_min(sum(rate(http_server_requests_seconds_count{application="$d"}[5m])), 0.0001)',
    "rps_5m": 'sum(rate(http_server_requests_seconds_count{application="$d"}[5m]))',
    "p95_seconds_5m": 'histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{application="$d"}[5m])))',
    "cpu_cores_5m": 'sum(rate(container_cpu_usage_seconds_total{namespace="$ns",pod=~"$d-.*",container!=""}[5m]))',
    "memory_mb": 'sum(container_memory_working_set_bytes{namespace="$ns",pod=~"$d-.*",container!=""}) / 1024 / 1024',
    "restarts_1h": 'sum(increase(kube_pod_container_status_restarts_total{namespace="$ns",pod=~"$d-.*"}[1h]))',
    "ready_replicas": 'sum(kube_deployment_status_replicas_ready{namespace="$ns",deployment="$d"})',
    "desired_replicas": 'sum(kube_deployment_spec_replicas{namespace="$ns",deployment="$d"})',
}


async def prom_query(client: httpx.AsyncClient, base: str, expr: str) -> float | None:
    try:
        r = await client.get(f"{base}/api/v1/query", params={"query": expr})
        r.raise_for_status()
        result = r.json()["data"]["result"]
        if not result:
            return None
        value = float(result[0]["value"][1])
        return None if value != value else round(value, 4)  # NaN -> None
    except Exception as exc:  # источник недоступен — это не повод падать
        log.warning("prometheus query failed: %s", exc)
        return None


async def collect_metrics(client, base: str, namespace: str, deployment: str) -> dict:
    names = list(QUERIES)
    exprs = [Template(QUERIES[n]).substitute(d=deployment, ns=namespace) for n in names]
    values = await asyncio.gather(*(prom_query(client, base, e) for e in exprs))
    return dict(zip(names, values))


async def collect_logs(client, base: str, selector_tpl: str, namespace: str, deployment: str,
                       lines: int, window_min: int) -> list[str]:
    selector = Template(selector_tpl).safe_substitute(namespace=namespace, deployment=deployment)
    query = f'{selector} |~ "(?i)(error|exception|warn|timeout|refused|failed)"'
    end = time.time_ns()
    start = end - window_min * 60 * 1_000_000_000
    try:
        r = await client.get(f"{base}/loki/api/v1/query_range", params={
            "query": query, "start": start, "end": end, "limit": lines, "direction": "backward"})
        r.raise_for_status()
        out: list[str] = []
        for stream in r.json()["data"]["result"]:
            for _, line in stream["values"]:
                out.append(redact(line.strip()))
        # одинаковые строки схлопываем, чтобы не тратить токены
        seen, uniq = set(), []
        for line in out:
            if line not in seen:
                seen.add(line)
                uniq.append(line)
        return uniq[:lines]
    except Exception as exc:
        log.warning("loki query failed: %s", exc)
        return []


def collect_kube_sync(apps, core, namespace: str, deployment: str) -> dict:
    """Состояние deployment'а, подов и событий. apps/core — клиенты kubernetes."""
    info: dict = {"deployments": {}, "pods": [], "events": []}
    try:
        for d in apps.list_namespaced_deployment(namespace).items:
            c = d.spec.template.spec.containers[0]
            info["deployments"][d.metadata.name] = {
                "replicas": d.spec.replicas or 0,
                "ready": d.status.ready_replicas or 0,
                "image": c.image,
                "generation": d.metadata.generation,
                "observed_generation": d.status.observed_generation,
            }
        # лейблы подов зависят от чарта, поэтому отбираем по имени: <deployment>-<hash>-<id>
        for p in core.list_namespaced_pod(namespace).items:
            if not (p.metadata.name or "").startswith(f"{deployment}-"):
                continue
            cs = (p.status.container_statuses or [None])[0]
            waiting = cs.state.waiting.reason if cs and cs.state and cs.state.waiting else None
            terminated = cs.last_state.terminated.reason if cs and cs.last_state and cs.last_state.terminated else None
            info["pods"].append({
                "name": p.metadata.name, "phase": p.status.phase,
                "restarts": cs.restart_count if cs else 0,
                "waiting_reason": waiting, "last_terminated_reason": terminated,
            })
        events = core.list_namespaced_event(namespace).items
        events = [e for e in events if deployment in (e.involved_object.name or "")]
        events.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp, reverse=True)
        for e in events[:8]:
            info["events"].append(redact(f"{e.type} {e.reason}: {e.message}", 250))
    except Exception as exc:
        log.warning("kubernetes query failed: %s", exc)
    return info


async def collect_all(settings, http: httpx.AsyncClient, kube, namespace: str, deployment: str) -> dict:
    metrics_t = collect_metrics(http, settings.prometheus_url, namespace, deployment)
    logs_t = collect_logs(http, settings.loki_url, settings.loki_selector, namespace, deployment,
                          settings.log_lines, settings.log_window_minutes)
    kube_t = asyncio.to_thread(kube, namespace, deployment) if kube else asyncio.sleep(0, result={"deployments": {}, "pods": [], "events": []})
    metrics, logs, kube_info = await asyncio.gather(metrics_t, logs_t, kube_t)
    return {"metrics": metrics, "logs": logs, **kube_info}

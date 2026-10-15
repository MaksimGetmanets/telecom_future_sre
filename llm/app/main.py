"""FastAPI: POST /diagnose, /healthz, /metrics."""
import hmac
import logging

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from .assistant import Assistant
from .config import Settings

log = logging.getLogger("llm")

DIAGNOSES = Counter("llm_diagnoses_total", "Диагнозы", ["action", "validated", "model"])
LATENCY = Histogram("llm_diagnose_seconds", "Время диагноза")


def make_kube():
    """Функция (namespace, deployment) -> dict или None, если мы вне кластера."""
    try:
        from kubernetes import client, config
        from .context import collect_kube_sync
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        apps, core = client.AppsV1Api(), client.CoreV1Api()
        return lambda ns, dep: collect_kube_sync(apps, core, ns, dep)
    except Exception as exc:
        log.warning("kubernetes недоступен: %s", exc)
        return None


def create_app(settings: Settings, assistant: Assistant | None = None) -> FastAPI:
    app = FastAPI(title="llm-assistant")
    state = {"assistant": assistant}

    def get() -> Assistant:
        if state["assistant"] is None:
            state["assistant"] = Assistant(settings, httpx.AsyncClient(timeout=10), make_kube())
        return state["assistant"]

    @app.get("/healthz")
    async def healthz():
        model = settings.anthropic_model if settings.provider == "anthropic" else settings.openai_model
        return {"status": "ok", "mode": "rules" if settings.mock else settings.provider, "model": model}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/diagnose")
    async def diagnose(request: Request, authorization: str | None = Header(default=None)):
        if settings.token:
            expected = f"Bearer {settings.token}"
            if not authorization or not hmac.compare_digest(authorization, expected):
                raise HTTPException(401, "unauthorized")
        body = await request.json()
        # принимаем и один алерт, и Alertmanager-payload (берём первый firing)
        alert = body
        if "alerts" in body:
            firing = [a for a in body["alerts"] if a.get("status", "firing") == "firing"]
            if not firing:
                raise HTTPException(422, "нет firing-алертов")
            alert = firing[0]
        if not alert.get("labels", {}).get("alertname"):
            raise HTTPException(422, "нет labels.alertname")
        with LATENCY.time():
            result = await get().diagnose(alert)
        DIAGNOSES.labels(result["suggested_action"]["type"], str(result["validated"]).lower(), result["model"]).inc()
        return result

    return app


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    return create_app(Settings.from_env())

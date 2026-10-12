"""HTTP-вход: вебхук Alertmanager, аудит, метрики."""
import hmac
from typing import Callable

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from . import audit, notify
from .config import Settings
from .engine import Engine
from .kube import Kube, RealKube
from .policies import PolicySet, load

ALERTS = Counter("remediator_alerts_received_total", "Алертов получено")
ACTIONS = Counter("remediator_actions_total", "Решения remediator", ["action", "status"])


def create_app(settings: Settings | None = None, kube: Kube | None = None, policies: PolicySet | None = None,
               notifier: Callable[[dict], None] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    policies = policies or load(settings.policy_file)
    if notifier is None and settings.telegram_token:
        notifier = lambda result: notify.send(settings.telegram_token, settings.telegram_chat_id, result)  # noqa: E731
    engine = Engine(policies, kube or RealKube(), settings.dry_run, notify=notifier)
    app = FastAPI(title="remediator")

    def check_token(authorization: str = Header(default="")):
        if settings.webhook_token and not hmac.compare_digest(authorization, f"Bearer {settings.webhook_token}"):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "dry_run": settings.dry_run, "policies": len(policies.policies)}

    @app.post("/alert", dependencies=[Depends(check_token)])
    def alert(payload: dict = Body(...)):
        ALERTS.inc(len(payload.get("alerts", [])))
        results = engine.handle(payload)
        for r in results:
            ACTIONS.labels(r["action"] or "none", r["status"]).inc()
        return {"results": results}

    @app.get("/audit", dependencies=[Depends(check_token)])
    def get_audit(limit: int = 50):
        return audit.recent(limit)

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def app_factory() -> FastAPI:
    return create_app()

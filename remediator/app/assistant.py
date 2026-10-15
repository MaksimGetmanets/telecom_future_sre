"""Необязательный LLM-советник. Работает в фоне и ничего не решает:
основное действие уже выбрано политикой, советник только дописывает диагноз в аудит."""
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import audit

log = logging.getLogger("remediator.assistant")


class Assistant:
    def __init__(self, url: str, token: str = "", timeout: float = 40.0, client: httpx.Client | None = None,
                 executor: ThreadPoolExecutor | None = None):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout)
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm-advice")

    def advise(self, alert: dict, result: dict) -> None:
        """Не блокирует обработку алерта и не бросает исключений."""
        try:
            self.executor.submit(self._run, alert, dict(result))
        except Exception:  # пул закрыт и т.п.
            log.exception("не удалось поставить диагноз в очередь")

    def _run(self, alert: dict, result: dict) -> None:
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            r = self.client.post(self.url, json=alert, headers=headers)
            r.raise_for_status()
            d = r.json()
        except Exception as exc:
            audit.record(event="llm_diagnosis", alertname=result.get("alertname"), deployment=result.get("deployment"),
                         status="unavailable", detail=f"{type(exc).__name__}: {exc}"[:200])
            return
        suggested = d.get("suggested_action") or {}
        # совпадение с политикой: то же действие на том же deployment
        agrees = suggested.get("type") == result.get("action") and suggested.get("deployment") == result.get("deployment")
        audit.record(
            event="llm_diagnosis", alertname=result.get("alertname"), deployment=result.get("deployment"),
            policy_action=result.get("action"), policy_status=result.get("status"),
            status="ok", hypothesis=d.get("hypothesis"), confidence=d.get("confidence"),
            evidence=d.get("evidence"), suggested=suggested, validated=d.get("validated"),
            rejected_reason=d.get("rejected_reason"), agrees=agrees, model=d.get("model"),
            latency_ms=d.get("latency_ms"), cached=d.get("cached"),
        )

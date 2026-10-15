"""Оркестратор: контекст -> промпт -> LLM -> проверка. Без ключа работает детерминированный режим."""
import json
import logging
import pathlib
import time
from string import Template

import httpx

from . import context as ctx
from . import anthropic_client, openai_client
from .openai_client import LLMError
from .redact import redact
from .schema import sanitize

log = logging.getLogger("llm.assistant")


def _fmt(value, empty="нет данных") -> str:
    if not value:
        return empty
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=None)


def mock_diagnosis(alertname: str, deployment: str, context: dict) -> dict:
    """Правила на случай, когда ключа нет или OpenAI недоступен. Помечается model='rules'."""
    m = context.get("metrics", {})
    err = m.get("error_ratio_5m") or 0
    cpu = m.get("cpu_cores_5m") or 0
    dep = context.get("deployments", {}).get(deployment, {})
    evidence = [f"{k}={v}" for k, v in m.items() if v is not None][:5]
    if cpu > 1.5 and err < 0.05:
        return {"hypothesis": "Высокая загрузка CPU без роста ошибок, вероятно нехватка реплик",
                "confidence": 0.6, "evidence": evidence, "action": "scale",
                "deployment": deployment, "replicas": dep.get("replicas", 1) + 1}
    if err >= 0.1 or "latency" in alertname.lower() or "error" in alertname.lower():
        return {"hypothesis": "Деградация сервиса без признаков нехватки ресурсов; помогает перезапуск",
                "confidence": 0.5, "evidence": evidence, "action": "restart",
                "deployment": deployment, "replicas": 0}
    return {"hypothesis": "Данных недостаточно для вывода", "confidence": 0.2,
            "evidence": evidence, "action": "none", "deployment": "", "replicas": 0}


class Assistant:
    def __init__(self, settings, http: httpx.AsyncClient, kube=None, clock=time.monotonic):
        self.s = settings
        self.http = http
        self.kube = kube
        self.clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}
        p = pathlib.Path(settings.prompts_dir)
        self.system_prompt = (p / "system.md").read_text(encoding="utf-8")
        self.user_tpl = Template((p / "user.md").read_text(encoding="utf-8"))

    def build_messages(self, alert: dict, context: dict) -> list[dict]:
        labels, ann = alert.get("labels", {}), alert.get("annotations", {})
        user = self.user_tpl.safe_substitute(
            alertname=labels.get("alertname", "?"), severity=labels.get("severity", "?"),
            summary=redact(ann.get("summary") or ann.get("description") or "", 300),
            namespace=labels.get("namespace", "?"), deployment=labels.get("deployment", "?"),
            targets=", ".join(self.s.allowed_targets),
            metrics=_fmt(context["metrics"]), deployments=_fmt(context["deployments"]),
            pods=_fmt(context["pods"]), events=_fmt("\n".join(context["events"])),
            logs=_fmt("\n".join(context["logs"])),
        )
        return [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}]

    async def diagnose(self, alert: dict) -> dict:
        labels = alert.get("labels", {})
        alertname = labels.get("alertname", "")
        namespace = labels.get("namespace", "")
        deployment = labels.get("deployment") or labels.get("app") or ""
        key = alert.get("fingerprint") or f"{alertname}/{namespace}/{deployment}"
        now = self.clock()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self.s.cache_ttl:
            return {**hit[1], "cached": True}

        context = await ctx.collect_all(self.s, self.http, self.kube, namespace, deployment)
        replicas = {n: d["replicas"] for n, d in context["deployments"].items()}
        known = list(context["deployments"]) or [deployment]

        meta = {"model": "rules", "latency_ms": 0, "tokens": None}
        error = None
        raw = None
        if not self.s.mock:
            try:
                messages = self.build_messages(alert, context)
                if self.s.provider == "anthropic":
                    raw, meta = await anthropic_client.chat_json(
                        self.http, base_url=self.s.anthropic_base_url, api_key=self.s.anthropic_api_key,
                        model=self.s.anthropic_model, messages=messages, timeout=self.s.openai_timeout)
                else:
                    raw, meta = await openai_client.chat_json(
                        self.http, base_url=self.s.openai_base_url, api_key=self.s.openai_api_key,
                        model=self.s.openai_model, messages=messages, timeout=self.s.openai_timeout)
            except LLMError as exc:
                error = str(exc)
                log.warning("LLM недоступен, использую правила: %s", exc)
        if raw is None:
            raw = mock_diagnosis(alertname, deployment, context)

        result = sanitize(
            raw, namespace=namespace, allowed_namespaces=self.s.allowed_namespaces,
            allowed_targets=self.s.allowed_targets, known_deployments=known,
            current_replicas=replicas, max_replicas=self.s.max_replicas)
        result.update(meta)
        result["alertname"] = alertname
        result["deployment"] = deployment
        result["namespace"] = namespace
        result["fallback_reason"] = error
        result["context_summary"] = {"metrics": context["metrics"], "log_lines": len(context["logs"]),
                                     "events": len(context["events"]), "pods": len(context["pods"])}
        self._cache[key] = (now, result)
        return {**result, "cached": False}

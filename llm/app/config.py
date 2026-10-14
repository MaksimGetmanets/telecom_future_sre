"""Настройки из переменных окружения."""
import os
import pathlib
from dataclasses import dataclass, field


def _bool(value, default=False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_timeout: float = 30.0
    # Провайдер: "openai" или "anthropic". Если не задан, выбирается по тому, у какого есть ключ
    provider: str = "openai"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-haiku-5-5"
    # Без ключа или с LLM_MOCK=true работает детерминированный режим (для демо без сети и для тестов)
    mock: bool = False
    prometheus_url: str = "http://kps-kube-prometheus-stack-prometheus.monitoring.svc:9090"
    loki_url: str = "http://loki.monitoring.svc:3100"
    # $namespace и $deployment подставляются из лейблов алерта; названия лейблов зависят от настройки Alloy
    loki_selector: str = '{namespace="$namespace", pod=~"$deployment-.*"}'
    log_lines: int = 40
    log_window_minutes: int = 15
    allowed_namespaces: list[str] = field(default_factory=lambda: ["demo"])
    # deployment'ы, над которыми ассистент вообще может предлагать действия
    allowed_targets: list[str] = field(default_factory=lambda: ["gateway", "orders"])
    max_replicas: int = 4
    cache_ttl: float = 120.0
    token: str = ""
    prompts_dir: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        key = e.get("OPENAI_API_KEY", "")
        akey = e.get("ANTHROPIC_API_KEY", "")
        provider = e.get("LLM_PROVIDER", "").strip().lower() or ("anthropic" if akey and not key else "openai")
        if provider not in ("openai", "anthropic"):
            raise ValueError(f"LLM_PROVIDER должен быть openai или anthropic, получено {provider!r}")
        active_key = akey if provider == "anthropic" else key
        default_prompts = str(pathlib.Path(__file__).resolve().parent.parent / "prompts")
        return cls(
            openai_api_key=key,
            openai_base_url=e.get("OPENAI_BASE_URL", cls.openai_base_url).rstrip("/"),
            openai_model=e.get("OPENAI_MODEL", cls.openai_model),
            openai_timeout=float(e.get("OPENAI_TIMEOUT", cls.openai_timeout)),
            provider=provider,
            anthropic_api_key=akey,
            anthropic_base_url=e.get("ANTHROPIC_BASE_URL", cls.anthropic_base_url).rstrip("/"),
            anthropic_model=e.get("ANTHROPIC_MODEL", cls.anthropic_model),
            mock=_bool(e.get("LLM_MOCK")) or not active_key,
            prometheus_url=e.get("PROMETHEUS_URL", cls.prometheus_url).rstrip("/"),
            loki_url=e.get("LOKI_URL", cls.loki_url).rstrip("/"),
            loki_selector=e.get("LOKI_SELECTOR", cls.loki_selector),
            log_lines=int(e.get("LOG_LINES", cls.log_lines)),
            log_window_minutes=int(e.get("LOG_WINDOW_MINUTES", cls.log_window_minutes)),
            allowed_namespaces=_list(e.get("ALLOWED_NAMESPACES"), ["demo"]),
            allowed_targets=_list(e.get("ALLOWED_TARGETS"), ["gateway", "orders"]),
            max_replicas=int(e.get("MAX_REPLICAS", cls.max_replicas)),
            cache_ttl=float(e.get("CACHE_TTL", cls.cache_ttl)),
            token=e.get("DIAGNOSE_TOKEN", ""),
            prompts_dir=e.get("PROMPTS_DIR", default_prompts),
        )

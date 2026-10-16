"""Настройки из переменных окружения."""
import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # По умолчанию dry-run: без явного DRY_RUN=false ничего в кластере не меняется
    dry_run: bool = True
    policy_file: str = "/etc/remediator/policies.yaml"
    # Если задан, вебхук требует заголовок Authorization: Bearer <token>
    webhook_token: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    # Если задан, после каждого решения в фоне запрашивается диагноз LLM-ассистента (только в аудит)
    llm_assistant_url: str = ""
    llm_assistant_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            dry_run=_bool(env.get("DRY_RUN"), True),
            policy_file=env.get("POLICY_FILE", "/etc/remediator/policies.yaml"),
            webhook_token=env.get("WEBHOOK_TOKEN", ""),
            telegram_token=env.get("TELEGRAM_TOKEN", ""),
            telegram_chat_id=env.get("TELEGRAM_CHAT_ID", ""),
            llm_assistant_url=env.get("LLM_ASSISTANT_URL", ""),
            llm_assistant_token=env.get("LLM_ASSISTANT_TOKEN", ""),
        )

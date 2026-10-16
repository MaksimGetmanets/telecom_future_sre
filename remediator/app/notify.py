"""Уведомление в Telegram (необязательное, best effort). Кнопки подтверждения живут в боте (tgbot/)."""
import logging

import httpx

log = logging.getLogger("remediator")

ICONS = {"executed": "✅", "dry_run": "🧪", "error": "❌"}


def format_message(result: dict) -> str:
    icon = ICONS.get(result["status"], "ℹ️")
    target = f'{result.get("namespace")}/{result.get("deployment")}'
    lines = [f'{icon} remediator: {result["action"]} {target}', f'алерт: {result["alertname"]}', f'статус: {result["status"]}']
    if result.get("detail"):
        lines.append(result["detail"])
    return "\n".join(lines)


def send(token: str, chat_id: str, result: dict) -> None:
    if not token or not chat_id:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": format_message(result)},
            timeout=3.0,
        )
    except Exception as exc:  # уведомление не должно ломать основную работу
        log.warning("telegram: не отправлено: %s", exc)

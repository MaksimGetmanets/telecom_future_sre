# Telegram-бот: принимает вебхук Alertmanager, дописывает ИИ-диагностику и показывает кнопки подтверждения действий
# (выполняет их remediator). Образ tgbot:dev должен быть в кластере (make tgbot-image) или берётся из реестра.
# Токен и chat id те же переменные, что у remediator (telegram_token, telegram_chat_id, см. remediator.tf).
# Без токена бот работает в режиме лога: kubectl -n monitoring logs deploy/tgbot.
# Чаты подключаются командой /start, поэтому chat id задавать необязательно.

variable "telegram_register_code" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Если задан, чат подключается только командой /start <код>"
}

resource "helm_release" "tgbot" {
  name      = "tgbot"
  namespace = "monitoring"
  chart     = "${path.module}/../tgbot/chart"
  timeout   = 300

  values = [yamlencode(merge({
    telegram        = { chatId = var.telegram_chat_id }
    remediatorUrl   = "http://remediator.monitoring.svc:8080"
    llmAssistantUrl = "http://llm-assistant.monitoring.svc:8080/diagnose"
  }, { for k, v in { image = local.images.tgbot } : k => v if local.use_registry }))]

  set_sensitive {
    name  = "telegram.token"
    value = var.telegram_token
  }

  set_sensitive {
    name  = "registerCode"
    value = var.telegram_register_code
  }

  depends_on = [helm_release.kps]
}

# remediator: принимает вебхук Alertmanager и перезапускает/масштабирует deployment'ы в namespace demo.
# Образ remediator:dev должен быть уже в кластере (make remediator-image).

variable "remediator_dry_run" {
  type    = bool
  default = true # включить реальные действия: terraform apply -var remediator_dry_run=false
}

variable "telegram_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "telegram_chat_id" {
  type    = string
  default = ""
}

resource "helm_release" "remediator" {
  name      = "remediator"
  namespace = "monitoring"
  chart     = "${path.module}/../remediator/chart"
  timeout   = 300

  values = [yamlencode({
    dryRun       = var.remediator_dry_run
    policiesYaml = file("${path.module}/../remediator/policies.yaml")
    telegram     = { chatId = var.telegram_chat_id }
    # советник включается, только когда задан ключ OpenAI (см. llm.tf)
    llmAssistantUrl = local.llm_enabled ? "http://llm-assistant.monitoring.svc:8080/diagnose" : ""
  })]

  set_sensitive {
    name  = "telegram.token"
    value = var.telegram_token
  }

  depends_on = [helm_release.kps, helm_release.demo_shop]
}

# LLM-ассистент. Образ llm-assistant:dev должен быть в кластере (make llm-image).
# Ключи не хранятся в git: export TF_VAR_anthropic_api_key=sk-ant-...  (или TF_VAR_openai_api_key=sk-...)
# Провайдер выбирается сам: если задан только один ключ, берётся он. Без ключей ассистент работает
# в режиме правил (model="rules"), а remediator его не вызывает.

variable "llm_provider" {
  type        = string
  default     = "" # "" = выбрать по тому, какой ключ задан; иначе openai или anthropic
  description = "openai | anthropic"
}

variable "openai_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "openai_model" {
  type    = string
  default = "gpt-4o-mini"
}

variable "openai_base_url" {
  type        = string
  default     = "https://api.openai.com/v1" # для шлюза: https://api.aitunnel.ru/v1 и т.п. (без /chat/completions)
  description = "База OpenAI-совместимого API"
}

variable "anthropic_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "anthropic_model" {
  type    = string
  default = "claude-haiku-5-5"
}

locals {
  llm_provider = var.llm_provider != "" ? var.llm_provider : (var.anthropic_api_key != "" && var.openai_api_key == "" ? "anthropic" : "openai")
  llm_key      = local.llm_provider == "anthropic" ? var.anthropic_api_key : var.openai_api_key
  llm_enabled  = local.llm_key != ""
}

resource "helm_release" "llm_assistant" {
  name      = "llm-assistant"
  namespace = "monitoring"
  chart     = "${path.module}/../llm/chart"
  timeout   = 300

  values = [yamlencode({
    provider  = local.llm_provider
    openai    = { model = var.openai_model, baseUrl = var.openai_base_url }
    anthropic = { model = var.anthropic_model }
    mock      = !local.llm_enabled
  })]

  set_sensitive {
    name  = "openai.apiKey"
    value = var.openai_api_key
  }

  set_sensitive {
    name  = "anthropic.apiKey"
    value = var.anthropic_api_key
  }

  depends_on = [helm_release.kps, helm_release.demo_shop]
}

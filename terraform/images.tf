# Откуда брать образы. Пусто (по умолчанию) = локальные образы :dev, как в k3d (make apps-images и т.п.).
# На ВМ: -var image_registry=ghcr.io/<владелец_в_нижнем_регистре>, образы публикует CI (sre-gateway, sre-orders,
# sre-remediator, sre-llm-assistant, sre-tgbot). Пакеты в ghcr должны быть публичными.

variable "image_registry" {
  type        = string
  default     = ""
  description = "Например ghcr.io/maksimgetmanets. Пусто = локальные образы"
}

variable "image_tag" {
  type        = string
  default     = "develop" # CI ставит тег по имени ветки (develop, main) и sha-<коммит>
  description = "Тег образов из реестра"
}

locals {
  use_registry = var.image_registry != ""
  images = {
    for name in ["gateway", "orders", "remediator", "llm-assistant", "tgbot"] : name => {
      repository = "${var.image_registry}/sre-${name}"
      tag        = var.image_tag
      pullPolicy = "Always"
    }
  }
}

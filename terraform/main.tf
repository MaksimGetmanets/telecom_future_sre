terraform {
  required_version = "~> 1.5"
  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
  }
}

variable "kube_config_path" {
  default = "~/.kube/config"
}

variable "kube_context" {
  default = "k3d-sre"
}

variable "grafana_admin_password" {
  type      = string
  default   = "prom-operator"
  sensitive = true
}

provider "helm" {
  kubernetes {
    config_path    = var.kube_config_path
    config_context = var.kube_context
  }
}

resource "helm_release" "kps" {
  name             = "kps"
  namespace        = "monitoring"
  create_namespace = true
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  timeout          = 900
  values           = [file("${path.module}/values/kps.yaml")]

  set_sensitive {
    name  = "grafana.adminPassword"
    value = var.grafana_admin_password
  }
}

resource "helm_release" "podinfo" {
  name             = "podinfo"
  namespace        = "demo"
  create_namespace = true
  repository       = "https://stefanprodan.github.io/podinfo"
  chart            = "podinfo"

  set {
    name  = "serviceMonitor.enabled"
    value = "true"
  }

  depends_on = [helm_release.kps]
}

resource "helm_release" "loki" {
  name       = "loki"
  namespace  = "monitoring"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki"
  timeout    = 600
  values     = [file("${path.module}/values/loki.yaml")]
  depends_on = [helm_release.kps]
}

resource "helm_release" "tempo" {
  name       = "tempo"
  namespace  = "monitoring"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "tempo"
  timeout    = 600
  depends_on = [helm_release.kps]
}

resource "helm_release" "alloy" {
  name       = "alloy"
  namespace  = "monitoring"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "alloy"
  timeout    = 600
  values     = [file("${path.module}/values/alloy.yaml")]
  depends_on = [helm_release.loki]
}

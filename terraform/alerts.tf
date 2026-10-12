# Правила алертов из observability/alerts (PrometheusRule). Хеш нужен, чтобы helm-провайдер заметил правки локального чарта.
locals {
  alerts_dir  = "${path.module}/../observability/alerts"
  alerts_hash = sha1(join("", [for f in sort(fileset(local.alerts_dir, "**")) : filesha1("${local.alerts_dir}/${f}")]))
}

resource "helm_release" "alerts" {
  name       = "alerts"
  namespace  = "monitoring"
  chart      = local.alerts_dir
  depends_on = [helm_release.kps]

  set {
    name  = "contentHash"
    value = local.alerts_hash
  }
}

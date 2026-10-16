# Дашборды Grafana из git: observability/dashboards/*.json -> ConfigMap с лейблом grafana_dashboard=1,
# его подхватывает sidecar Grafana из kube-prometheus-stack (namespace monitoring).

locals {
  dashboards_dir = "${path.module}/../observability/dashboards"
  # Хеш всех файлов чарта: без него helm-провайдер не замечает правок в локальном чарте
  dashboards_hash = sha1(join("", [for f in sort(fileset(local.dashboards_dir, "**")) : filesha1("${local.dashboards_dir}/${f}")]))
}

resource "helm_release" "dashboards" {
  name       = "dashboards"
  namespace  = "monitoring"
  chart      = local.dashboards_dir
  depends_on = [helm_release.kps]

  set {
    name  = "contentHash"
    value = local.dashboards_hash
  }
}

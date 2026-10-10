# Demo-магазин (gateway, orders, postgres) из локального Helm-чарта apps/chart.
# Образы gateway:dev и orders:dev должны быть уже в кластере (см. apps/apps.mk: make apps-images).
# ServiceMonitor-ресурсам нужны CRD из kube-prometheus-stack, поэтому depends_on.

variable "postgres_password" {
  type      = string
  default   = "orders"
  sensitive = true
}

resource "helm_release" "demo_shop" {
  name             = "demo-shop"
  namespace        = "demo"
  create_namespace = true
  chart            = "${path.module}/../apps/chart"
  timeout          = 600

  set_sensitive {
    name  = "postgres.password"
    value = var.postgres_password
  }

  depends_on = [helm_release.kps]
}

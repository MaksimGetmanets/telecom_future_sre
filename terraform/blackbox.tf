# Blackbox Exporter: внешние (синтетические) пробы бизнес-ручек demo-shop.
# Сами пробы (ресурсы Probe) и правила алертов лежат в чарте observability/alerts/templates/synthetic.yaml,
# дашборд в observability/dashboards/synthetic.json.
# fullnameOverride фиксирует имя сервиса: blackbox-exporter.monitoring.svc:9115, на него смотрят ресурсы Probe.
resource "helm_release" "blackbox_exporter" {
  name       = "blackbox-exporter"
  namespace  = "monitoring"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus-blackbox-exporter"
  depends_on = [helm_release.kps]

  values = [yamlencode({
    fullnameOverride = "blackbox-exporter"
    config = {
      modules = {
        # Проба успешна, если ответ 2xx быстрее таймаута
        http_2xx = {
          prober  = "http"
          timeout = "5s"
          http = {
            method                = "GET"
            preferred_ip_protocol = "ip4"
            follow_redirects      = true
          }
        }
      }
    }
  })]
}

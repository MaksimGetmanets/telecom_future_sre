# SLO как код (Sloth)

| Сервис | SLO | Цель | Алерт | Действие remediator |
|---|---|---|---|---|
| gateway | availability: ответ без 5xx на `/orders*` | 99.5% | `GatewayAvailabilityBurn` | restart gateway |
| gateway | latency: быстрее 300 мс (`le="0.3"`) | 95% | `GatewayLatencyBurn` | нет (только уведомление) |
| orders | availability | 99.5% | `OrdersAvailabilityBurn` | restart orders |
| orders | latency | 95% | `OrdersLatencyBurn` | scale orders (+1, максимум 4) |

Цели черновые, финальные значения у PM. Спецификации: `gateway.yaml`, `orders.yaml`.

## Как это работает

1. `make slo-gen` превращает спецификации в правила Prometheus: `observability/alerts/generated/sloth-*.yaml` (лежат в git, перегенерируйте и закоммитьте после правок).
2. `make up` (или `terraform apply`) кладёт их в кластер как `PrometheusRule` через чарт `observability/alerts`.
3. Алерт приходит в Alertmanager с лейблами `namespace=demo`, `deployment`, `severity=page`; маршрут из `terraform/values/alertmanager.yaml` отправляет его в remediator.

## Окна алертов

`windows/demo.yaml` заменяет стандартные окна Google SRE (1 ч / 5 мин и т. д.) короткими: при 50% ошибок алерт срабатывает примерно через минуту. Для боевого профиля уберите `--slo-period-windows-path` из `slo.mk`.
Алерты по задержке срабатывают, когда медленными оказывается большинство запросов (порог около 86% при цели 95%): для проверки используйте `chaos/fault.sh orders 'delayMs=600'`.
Ticket-алерты отключены (`ticket_alert.disable`): для демо нужен только page.

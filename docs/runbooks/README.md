# Runbook'и

Инструкции по топ-5 инцидентам demo-сервиса (`gateway → orders → PostgreSQL`, namespace `demo`).
Каждый алерт ссылается на свой runbook через аннотацию `runbook_url`.

Что сверено с репозиторием: namespace `demo`; deployment'ы `gateway` и `orders` (по 2 реплики); statefulset `postgres`;
лейбл подов `app.kubernetes.io/name=<имя>`; значения `severity` в алертах: `page` и `ticket`.

## Соответствие алертов и runbook'ов

| Runbook | Инцидент | Алерты | Severity | Автодействие (remediator) |
|---|---|---|---|---|
| [RB-01](rb-01-pod-down.md) | Под упал / не готов | `GatewayAvailabilityBurn`, `OrdersAvailabilityBurn`; **нужно добавить:** `DemoPodNotReady` | page | restart; откат вручную |
| [RB-02](rb-02-high-latency.md) | Рост латентности p95 | `DemoHighLatency`, `OrdersLatencyBurn`, `GatewayLatencyBurn` | page | scale orders (+1, максимум 4); для gateway нет |
| [RB-03](rb-03-error-spike.md) | Всплеск 5xx | `DemoHighErrorRate`, `OrdersAvailabilityBurn`, `GatewayAvailabilityBurn` | page | restart; откат вручную |
| [RB-04](rb-04-memory-leak.md) | Утечка памяти / OOMKilled | `DemoMemoryHigh`; **нужно добавить:** `DemoContainerOOMKilled` | ticket / page | restart (пауза 180 с, максимум 6 в час) |
| [RB-05](rb-05-network-dependency.md) | Деградация сети / зависимость недоступна | **нужно добавить:** `DemoProbeFailed`; косвенно `GatewayAvailabilityBurn`, `GatewayLatencyBurn` | page | нет (только уведомление), см. предупреждение в RB-05 |

Алерты, помеченные «нужно добавить», в репозитории пока не существуют. Остальные уже заданы в `observability/slo/*.yaml`
и `observability/alerts/templates/demo-shop.yaml`.

## Как подключить `runbook_url`

Сейчас в репозитории аннотации указывают на старые имена файлов. Нужно заменить:

| Было | Стало |
|---|---|
| `docs/runbooks/high-error-rate.md` | `docs/runbooks/rb-03-error-spike.md` |
| `docs/runbooks/high-latency.md` | `docs/runbooks/rb-02-high-latency.md` |
| `docs/runbooks/memory-leak.md` | `docs/runbooks/rb-04-memory-leak.md` |

Для SLO-алертов (Sloth, `observability/slo/*.yaml`; после правки выполните `make slo-gen` и закоммитьте результат):

```yaml
alerting:
  name: OrdersLatencyBurn
  page_alert:
    labels: { severity: page }
    annotations:
      runbook_url: https://github.com/MaksimGetmanets/telecom_future_sre/blob/main/docs/runbooks/rb-02-high-latency.md
  ticket_alert:
    disable: true      # в демо нужен только page
```

Для обычных Prometheus-правил (`observability/alerts/templates/`). Лейблы `namespace` и `deployment` обязательны:
по ним remediator выбирает цель действия.

```yaml
- alert: DemoPodNotReady
  expr: kube_pod_status_ready{namespace="demo", condition="true"} == 0
  for: 2m
  labels: { severity: page, namespace: demo, deployment: orders }
  annotations:
    summary: "Под {{ $labels.pod }} не готов"
    runbook_url: https://github.com/MaksimGetmanets/telecom_future_sre/blob/main/docs/runbooks/rb-01-pod-down.md
```

Проверка в CI (пока не реализована): каждый алерт в `observability/` содержит `runbook_url`, и файл по ссылке существует.

Шаблон нового runbook: [_template.md](_template.md).

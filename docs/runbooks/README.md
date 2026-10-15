# Runbook'и

Инструкции по топ-5 инцидентам demo-сервиса (`gateway → orders → PostgreSQL`, namespace `demo`) плюс отдельный runbook по внешним пробам.
Каждый алерт ссылается на свой runbook через аннотацию `runbook_url`.

Что сверено с репозиторием: namespace `demo`; deployment'ы `gateway` и `orders` (по 2 реплики); statefulset `postgres`;
лейбл подов `app.kubernetes.io/name=<имя>`; метки логов Loki `namespace`, `app`, `pod`; метки метрик приложений `application`;
значения `severity` в алертах: `page` и `ticket`; пороги SLO из `docs/slo.md`.

## Соответствие алертов и runbook'ов

| Runbook | Инцидент | Алерты | Severity | Автодействие (remediator) |
|---|---|---|---|---|
| [RB-01](rb-01-pod-down.md) | Под упал / не готов | `GatewayAvailabilityBurn`, `OrdersAvailabilityBurn`, `SyntheticProbeFailed` | page | restart (кроме проб: только уведомление); откат по кнопке |
| [RB-02](rb-02-high-latency.md) | Рост латентности p95 | `DemoHighLatency`, `OrdersLatencyBurn`, `GatewayLatencyBurn` | page | `DemoHighLatency`: restart; `OrdersLatencyBurn`: scale orders (+1, максимум 4); gateway: нет |
| [RB-03](rb-03-error-spike.md) | Всплеск 5xx | `DemoHighErrorRate`, `OrdersAvailabilityBurn`, `GatewayAvailabilityBurn` | page | restart; откат по кнопке |
| [RB-04](rb-04-memory-leak.md) | Утечка памяти / OOMKilled | `DemoMemoryHigh` | ticket | restart (пауза 180 с, максимум 6 в час) |
| [RB-05](rb-05-network-dependency.md) | Деградация сети / зависимость недоступна | `SyntheticProbeFailed`, `SyntheticSloBurn`, `*LatencyBurn` | page | нет осмысленного (рестарт не лечит сеть), см. RB-05 |
| [Пробы](synthetic-probe-failed.md) | Внешняя проба не проходит | `SyntheticProbeFailed`, `SyntheticSloBurn` | page | нет, только уведомление |

Отдельного алерта на OOMKilled и на «под не готов» нет: такие случаи ловят алерты доступности и пробы, детали в RB-01 и RB-04.

## Как подключён `runbook_url`

В каждом алерте аннотация `runbook_url` указывает на файл из этого каталога:

- алерты Sloth (`observability/slo/*.yaml`, результат в `observability/alerts/generated/`, пересборка `make slo-gen`): `rb-02-high-latency.md`, `rb-03-error-spike.md`;
- правила Prometheus (`observability/alerts/templates/`): `demo-shop.yaml` (`rb-02`, `rb-03`, `rb-04`) и `synthetic.yaml` (`synthetic-probe-failed.md`).

Новый алерт: добавьте аннотацию `runbook_url: docs/runbooks/<файл>.md` и лейблы `namespace` и `deployment` (по ним remediator выбирает цель действия).
Структура runbook'а: симптомы и влияние, диагностика, автоматическое действие, ручные шаги, проверка восстановления, откат и риски, эскалация, действия после инцидента.
Проверка в CI (каждый алерт содержит `runbook_url`, файл по ссылке существует) пока не реализована.

# RB-02: Рост латентности p95

**Алерты:** `DemoHighLatency`, `OrdersLatencyBurn`, `GatewayLatencyBurn` · **Severity:** page
**Затронутый SLO:** latency (95% запросов быстрее 300 мс)
**Владелец:** команда проекта (Володин А., Гетманец М.) · **Последняя проверка:** 14.10.2026 (ручка `delayMs=600`, замер MTTR на ВМ) и 15.10.2026 (Chaos Mesh `orders-cpu-stress`)

## 1. Симптомы и влияние
- Запросы выполняются дольше порога 300 мс, пользователь видит медленные ответы.
- Бюджет по латентности сгорает быстрее нормы (burn rate > 1).
- Ошибок может не быть: сервис «жив», но медленный.

## 2. Диагностика
1. Дашборд «Demo Shop: SLO / SLI»: панели «Latency p95», «Latency p50 / p95 / p99», «Быстрые запросы (<300 мс)»; сервис выбирается переменной.
2. PromQL (p95 по сервису):
   ```
   histogram_quantile(0.95,
     sum by (le) (rate(http_server_requests_seconds_bucket{application="gateway", uri=~"/orders.*"}[5m])))
   ```
   Норма на небольшой нагрузке около 5 мс, порог SLO 0,3 с (см. `docs/slo.md`).
3. Нагрузка и ресурсы:
   - `sum(rate(container_cpu_usage_seconds_total{namespace="demo"}[5m])) by (pod)` рядом с limits
   - `sum(rate(http_server_requests_seconds_count{application="gateway", uri=~"/orders.*"}[5m]))`: вырос ли трафик
4. Трейс: в Grafana → Explore → Tempo найти трейс с большой длительностью (по `service.name` и длительности) и посмотреть, какой span (gateway, orders или БД) даёт задержку.
5. Логи: в строках JSON-логов есть `trace_id`, в Grafana (Loki) он открывается ссылкой «Открыть трейс». Запрос: `{namespace="demo", app="orders"} |= "<trace_id>"`.
6. Типичные причины: ручка `/slow` или `delayMs` через `/fault`, CPU-stress (Chaos Mesh `StressChaos`), всплеск трафика, медленные запросы к БД, сетевая задержка (RB-05).

## 3. Автоматическое действие (remediator)
- `DemoHighLatency`: `restart` затронутого deployment. Задержка из `chaos/fault.sh` живёт в памяти пода, добавление реплик её не снимает, поэтому для этого алерта выбран перезапуск (проверено замерами, см. `docs/results/mttr.md`).
- `OrdersLatencyBurn`: `scale` orders на +1 реплику (максимум 4). Для `GatewayLatencyBurn` действия нет: задержка gateway обычно приходит от orders, уведомление идёт только в Telegram.
- Режим: dry-run по умолчанию. ИИ-ассистент в Telegram может предложить `restart`, `scale` или `rollback`, действие выполняется после нажатия кнопки.
- Лимиты: пауза 180 с, не более 6 действий в час на deployment, потолок реплик 4.
- Не масштабировать, если причина в БД или сети (см. RB-05): больше реплик усилит нагрузку на базу, а задержка Chaos Mesh сохранится на новых подах.

## 4. Ручные шаги
```bash
kubectl -n demo top pods
kubectl -n demo scale deploy/<name> --replicas=3
# если идёт эксперимент Chaos Mesh и он не нужен (виды удаляйте отдельными командами):
kubectl -n demo delete stresschaos <name>
kubectl -n demo delete networkchaos <name>
# сбой, внесённый ручкой, снять:
chaos/fault.sh orders clear
```
Если причина в релизе: `kubectl -n demo rollout undo deploy/<name>`.

## 5. Проверка восстановления
- p95 < 0,3 с на протяжении 10 минут.
- Burn rate вернулся ниже порога, алерт resolved.

## 6. Откат и риски
- Лишние реплики съедают ресурсы узла; после стабилизации вернуть прежнее число (`scale ... --replicas=<N>`).
- Скейл не лечит медленный код, БД или сеть, только нехватку CPU.
- Замер на ВМ: MTTR при `delayMs=600` с remediator около 146 с.

## 7. Эскалация
Если p95 не улучшился за 10 минут после действия: искать узкое место по трейсу и подключать владельца соответствующего сервиса.

## 8. После инцидента
Зафиксировать причину и время; если порог срабатывал по нормальному трафику, пересмотреть SLO по результатам k6.

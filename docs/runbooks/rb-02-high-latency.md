# RB-02: Рост латентности p95

**Алерты:** `DemoLatencyBurnPage` (critical), `DemoLatencyBurnTicket` (warning)
**Затронутый SLO:** latency p95 (95% запросов < 500 мс)
**Владелец:** <кто> · **Последняя проверка:** <дата, `/slow` и Chaos Mesh CPU-stress>

## 1. Симптомы и влияние
- Запросы выполняются дольше порога 500 мс, пользователь видит медленные ответы.
- Бюджет по латентности сгорает быстрее нормы (burn rate > 1).
- Ошибок может не быть: сервис «жив», но медленный.

## 2. Диагностика
1. Дашборд «Demo / Latency»: p95 по gateway и orders отдельно, чтобы понять, где задержка.
2. PromQL (p95 по сервису):
   ```
   histogram_quantile(0.95,
     sum by (le) (rate(http_server_requests_seconds_bucket{namespace="demo", app="gateway"}[5m])))
   ```
   Норма: см. baseline в README (SLO-порог 0,5 с).
3. Нагрузка и ресурсы:
   - `sum(rate(container_cpu_usage_seconds_total{namespace="demo"}[5m])) by (pod)` рядом с limits
   - `rate(http_server_requests_seconds_count{app="gateway"}[5m])` — вырос ли трафик
4. Трейс: в Tempo найти трейс с большой длительностью (от метрики через exemplar или по `service.name` и duration > 500ms); определить, какой span (gateway, orders или БД) даёт задержку.
5. Логи: `{namespace="demo"} |= "<trace_id>"`.
6. Типичные причины: активна ручка `/slow`, CPU-stress (Chaos Mesh `StressChaos`), всплеск трафика, медленные запросы к БД.

## 3. Автоматическое действие (Remediator)
- Действие: `scale up` затронутого deployment на +1 реплику (максимум 3).
- Режим: dry-run по умолчанию; подтверждение в Telegram для critical.
- Лимиты: не чаще 1 раза за 10 минут, потолок реплик 3.
- Не масштабируем, если причина в БД (см. RB-05): больше реплик усилит нагрузку на базу.

## 4. Ручные шаги
```bash
kubectl -n demo top pods
kubectl -n demo scale deploy/<name> --replicas=3
# если идёт Chaos-эксперимент и он не нужен:
kubectl -n <chaos-ns> delete stresschaos <name>
```
Если причина в релизе: `kubectl -n demo rollout undo deploy/<name>`.

## 5. Проверка восстановления
- p95 < 0,5 с на протяжении 10 минут.
- Burn rate вернулся ниже порога, алерт resolved.

## 6. Откат и риски
- Лишние реплики съедают ресурсы узла; после стабилизации вернуть прежнее число (`scale ... --replicas=<N>`).
- Скейл не лечит медленный код или БД, только нехватку CPU.

## 7. Эскалация
Если p95 не улучшился за 10 минут после скейла: искать узкое место по трейсу и подключать владельца соответствующего сервиса.

## 8. После инцидента
Зафиксировать причину и время; если порог срабатывал по нормальному трафику, пересмотреть SLO по результатам k6.

# RB-03: Всплеск ошибок 5xx

**Алерты:** `DemoHighErrorRate`, `OrdersAvailabilityBurn`, `GatewayAvailabilityBurn` · **Severity:** page
**Затронутый SLO:** доступность (≥ 99,5% запросов без 5xx; отдельного SLO «error rate» нет, это тот же SLI)
**Владелец:** команда проекта (Володин А., Гетманец М.) · **Последняя проверка:** 15.10.2026, `chaos/fault.sh orders 'errorRate=0.5'` на ВМ (MTTR 118–139 с)

## 1. Симптомы и влияние
- Доля ответов 5xx выше нормы, бюджет ошибок быстро расходуется.
- Пользователи получают ошибки на части или на всех запросах.
- Когда горит `DemoHighErrorRate` (orders), алерты gateway и внешних проб отдельно не приходят: `inhibit_rules` в Alertmanager подавляют симптомы, пока горит причина.

## 2. Диагностика
1. Дашборд «Demo Shop: SLO / SLI»: «Доля ошибок 5xx», «Ошибки 5xx/с по URI».
2. PromQL:
   ```
   sum(rate(http_server_requests_seconds_count{application="orders", uri=~"/orders.*", status=~"5.."}[5m]))
   / sum(rate(http_server_requests_seconds_count{application="orders", uri=~"/orders.*"}[5m]))
   ```
3. Определить источник: ошибки в `gateway` (проброс от `orders` или собственные) или в `orders` (сравнить `application="gateway"` и `application="orders"`).
4. Трейс: Grafana → Explore → Tempo, фильтр по статусу ошибки; посмотреть, в каком span возникло исключение.
5. Логи: `{namespace="demo", app="orders"} |= "ERROR"`, найти `trace_id` и открыть трейс ссылкой в Grafana.
6. Проверить, не было ли релиза: `kubectl -n demo rollout history deploy/<name>`.
7. Типичные причины: ручка `/fail` или `/fault`, плохой релиз, недоступна БД (RB-05).

## 3. Автоматическое действие (remediator)
1. `restart` затронутого deployment (политика `restart-on-errors`: `DemoHighErrorRate`, `*AvailabilityBurn`).
2. Если после рестарта ошибки остались или всплеск начался сразу после релиза: `rollback` на предыдущую ревизию. Автоматически он не выполняется: ИИ-ассистент предлагает его в Telegram, выполнение после нажатия кнопки. Откат не трогает ревизии, отличающиеся от текущей только меткой перезапуска.
- Режим: dry-run по умолчанию.
- Лимиты: пауза 180 с, не более 6 действий в час на deployment.
- Важно: алерты по окну 30 мин (`*AvailabilityBurn`) горят долго после устранения сбоя и могут вызвать лишний рестарт на здоровом сервисе (см. `docs/chaos.md`). Лимит и пауза ограничивают ущерб.

## 4. Ручные шаги
```bash
kubectl -n demo rollout restart deploy/orders
kubectl -n demo rollout status deploy/orders
kubectl -n demo rollout undo deploy/orders    # если рестарт не помог
```
Если ошибки вызваны ручкой `/fail` или `/fault` в рамках демо: `chaos/fault.sh orders clear`.

## 5. Проверка восстановления
- Доля 5xx вернулась к норме (< 0,5%) минимум на 10 минут.
- Алерт resolved; в логах нет новых ERROR с тем же стеком.

## 6. Откат и риски
- Откат возвращает старую версию: убедиться, что она совместима со схемой БД.
- Рестарт обрывает in-flight запросы.

## 7. Эскалация
Ошибки не уходят после отката: проверить БД (RB-05) и привлечь владельца сервиса.

## 8. После инцидента
Записать причину (релиз, зависимость, внешний фактор), добавить тест или алерт, если ошибку поймали поздно.

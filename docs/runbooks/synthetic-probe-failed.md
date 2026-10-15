# Runbook: SyntheticProbeFailed / SyntheticSloBurn

Алерты срабатывают, когда внешняя проба Blackbox Exporter не получает ответ 2xx на `GET /orders`
(через сервис gateway или напрямую orders). Это взгляд снаружи: приложение может быть «живым» по метрикам, но недоступным клиенту.

## Что значит алерт
- `SyntheticProbeFailed`: проба падает 30 секунд подряд.
- `SyntheticSloBurn`: доля неудачных проб за окно выше порога, бюджет SLO 99,5% сгорает быстро (окна 1 м и 5 м, либо 5 м и 30 м).

## Диагностика (5 минут)
1. Какая проба: лейбл `service` в алерте (`gateway` или `orders`). Дашборд Grafana «Синтетика: пробы Blackbox».
2. Причина сбоя пробы: `probe_http_status_code` (0 = нет ответа, 5xx = ошибка приложения), `probe_duration_seconds` (таймаут 5 с).
3. Сама проба или приложение? Если `probe_success` падает у обоих сервисов сразу, проверьте Blackbox Exporter:
   `kubectl -n monitoring get pods -l app.kubernetes.io/name=prometheus-blackbox-exporter`.
4. Приложение: `kubectl -n demo get pods`, `kubectl -n demo logs deploy/<service> --tail=50`.
5. Связанные алерты: `DemoHighErrorRate`, `*AvailabilityBurn` (remediator мог уже перезапустить сервис, см. `/audit`).

## Действия
- Под в `CrashLoopBackOff` или `ImagePullBackOff`: смотрите `kubectl -n demo describe pod`, откатите релиз (`kubectl -n demo rollout undo deploy/<service>`).
- Ошибки 5xx на orders: см. `docs/runbooks/rb-03-error-spike.md` (перезапуск делает remediator).
- Таймауты без ошибок в логах: перегрузка, см. `docs/runbooks/rb-02-high-latency.md`.
- Пробы падают, а приложение отвечает вручную (`curl http://gateway.demo.svc:8080/orders` из пода): проблема в Blackbox Exporter или сети, перезапустите его.

## После инцидента
Запишите время, причину и действие в журнал инцидентов; если сработал remediator, проверьте запись в audit log.

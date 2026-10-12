# remediator

Принимает вебхук Alertmanager и выполняет действие над deployment'ом: **restart** (как `kubectl rollout restart`) или **scale** (+N реплик до потолка).
Действие в алерте не передаётся: его выбирает таблица политик `policies.yaml` по лейблам алерта.

```
Prometheus rule → Alertmanager → POST /alert → политика → предохранители → действие → аудит (stdout → Loki) + Telegram
```

## Контракт с алертами

| Что | Значение |
|---|---|
| Лейблы | `alertname`, `namespace` (=`demo`), `deployment` (статический), `severity` |
| Аннотация | `runbook_url` |
| Цель действия | `namespace` + `deployment` из лейблов алерта |

Алерты без `namespace`/`deployment` пропускаются (`skipped_no_target`). Для Sloth-алертов `deployment` задаётся статическим лейблом в spec каждого сервиса.

## Предохранители

- **dry-run по умолчанию** (`DRY_RUN=true`): решение пишется в аудит, кластер не меняется.
- `allowed_namespaces`: чужие namespace не трогаем.
- `cooldown_seconds`: пауза между одинаковыми действиями над одним deployment.
- `max_actions_per_hour`: потолок на deployment.
- RBAC: Role только в `demo`, только `deployments` (get/list/patch) и `deployments/scale` (get/patch).
- `scale` не выше `params.max`.
- Счётчики cooldown и лимита хранятся в памяти: после перезапуска remediator они обнуляются.

## Статусы решений

`executed`, `dry_run`, `error`, `skipped_not_firing`, `skipped_no_policy`, `skipped_no_target`, `skipped_namespace`, `skipped_guard`, `skipped_at_max`.
Каждое решение — одна JSON-строка в stdout и запись в `GET /audit`; метрики `remediator_alerts_received_total` и `remediator_actions_total{action,status}` на `/metrics`.

## Запуск

```bash
make remediator-test      # тесты в контейнере
make up                   # поднимет всё, включая remediator (dry-run)
kubectl -n monitoring port-forward svc/remediator 8088:8080 &
make remediator-fire      # тестовый алерт; смотрим ответ и логи
kubectl -n monitoring logs deploy/remediator
```

Включить реальные действия:

```bash
cd terraform && terraform apply -auto-approve -var remediator_dry_run=false
```

Сценарий end-to-end (после включения реальных действий):

```bash
kubectl -n demo port-forward svc/gateway 8080:8080 &
while true; do curl -s -o /dev/null localhost:8080/orders; sleep 0.2; done &   # фоновый трафик, без него алерт не сработает
chaos/fault.sh orders 'errorRate=0.5'    # сбой на всех подах orders
kubectl -n demo get pods -w              # через 1-2 минуты поды orders перезапустятся, сбой исчезнет
chaos/fault.sh orders clear              # если нужно снять вручную
```

## Telegram

Переменные `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ID` (через `-var telegram_token=... -var telegram_chat_id=...`): remediator пишет в чат о каждом `executed`/`dry_run`/`error`. Кнопка подтверждения — следующий шаг.

## Политики

См. `policies.yaml`. `match` — лейбл → регулярное выражение (полное совпадение), первая подошедшая политика выигрывает. Правка файла + `terraform apply` перезапускает под remediator.

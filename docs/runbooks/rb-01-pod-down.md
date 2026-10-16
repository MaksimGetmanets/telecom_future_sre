# RB-01: Под упал / не готов

**Алерты:** `SyntheticProbeFailed`, `GatewayAvailabilityBurn`, `OrdersAvailabilityBurn` · **Severity:** page
**Затронутый SLO:** доступность (99,5% запросов без 5xx), синтетическая доступность (99,5% успешных проб)
**Владелец:** команда проекта (Володин А., Гетманец М.) · **Последняя проверка:** 15.10.2026, Chaos Mesh `orders-pod-kill` на ВМ

## 1. Симптомы и влияние
- Внешняя проба Blackbox (`probe_success`) падает в 0 или мигает.
- Gateway отвечает 502/503, либо запросы к `orders` завершаются ошибкой.
- На дашборде «Demo Shop: здоровье сервиса и логи»: падает панель «Pod Ready», растут «Рестарты за период»; на «Demo Shop: SLO / SLI» растёт доля 5xx.
- При 2 репликах влияние кратковременное; при 1 реплике сервис недоступен до перезапуска.
- Замер (pod-kill всех подов `orders`, 15.10.2026): проба падала через 5 с, простой по пробам около 42 с, Kubernetes пересоздал поды сам. Алерт `SyntheticProbeFailed` не сработал: простой короче порога `for: 30s` вместе с интервалом сбора метрик.

## 2. Диагностика
1. Дашборды «Demo Shop: здоровье сервиса и логи» и «Синтетика: пробы Blackbox».
2. PromQL:
   - `kube_deployment_status_replicas_available{namespace="demo"}`: должно совпадать с желаемым числом
   - `increase(kube_pod_container_status_restarts_total{namespace="demo"}[15m])`: рост означает CrashLoop
   - `probe_success{service="gateway"}`
3. Причина падения:
   ```bash
   kubectl -n demo get pods -o wide
   kubectl -n demo describe pod <pod>      # Events: OOMKilled, Evicted, ImagePull, Probe failed
   kubectl -n demo logs <pod> --previous   # лог перед падением
   ```
4. Логи в Loki (Grafana → Explore): `{namespace="demo", app="orders"} |= "ERROR"` за момент падения.
5. Если идёт эксперимент Chaos Mesh: `kubectl get podchaos,networkchaos,stresschaos -A`.

## 3. Автоматическое действие (remediator)
- Если под просто убит (pod-kill): Kubernetes пересоздаст его сам, remediator **ничего не делает**, ждите 1–2 минуты.
- `GatewayAvailabilityBurn` и `OrdersAvailabilityBurn`: remediator делает `restart` deployment (политика `restart-on-errors`). `SyntheticProbeFailed` политики не имеет: только уведомление в Telegram.
- Режим: dry-run по умолчанию, в боевом режиме нужен `TF_VAR_remediator_dry_run=false` при каждом `make deploy`.
- Лимиты: пауза 180 с между одинаковыми действиями над одним deployment, не более 6 действий в час, только namespace `demo`.
- Откат (`rollback`) автоматически не выполняется. Его предлагает ИИ-ассистент в Telegram, выполняется после нажатия кнопки «Выполнить».
- Журнал: `kubectl get --raw /api/v1/namespaces/monitoring/services/remediator:8080/proxy/audit` (решения автоматики и ручные подтверждения `manual_remediation`).

## 4. Ручные шаги
```bash
kubectl -n demo rollout restart deploy/<name>
kubectl -n demo rollout status deploy/<name> --timeout=120s
# если падение началось после релиза:
kubectl -n demo rollout undo deploy/<name>
# если не хватает реплик:
kubectl -n demo scale deploy/<name> --replicas=2
```

## 5. Проверка восстановления
- Число Ready-реплик равно желаемому.
- `probe_success == 1` минимум 5 минут.
- Алерт перешёл в resolved, доля 5xx вернулась к норме.

## 6. Откат и риски
- Рестарт при единственной реплике даёт простой на время старта (≈ 30–60 с). Для демо держите 2 реплики.
- `rollout undo` откатывает на предыдущую ревизию; убедитесь, что она рабочая (`kubectl rollout history`).

## 7. Эскалация
Не восстановилось за 10 минут: связаться с владельцем сервиса; если проблема в узле (`NotReady`, `Evicted`): с отвечающим за инфраструктуру (Ansible/k3s).

## 8. После инцидента
Записать время начала, обнаружения и восстановления (для MTTR); если причина в нехватке ресурсов, пересмотреть requests/limits.

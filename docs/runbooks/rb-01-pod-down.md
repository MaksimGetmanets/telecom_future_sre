# RB-01: Под упал / не готов

**Алерты:** `DemoPodNotReady`, `DemoAvailabilityBurnPage` · **Severity:** critical
**Затронутый SLO:** availability
**Владелец:** <кто> · **Последняя проверка:** <дата, Chaos Mesh pod-kill>

## 1. Симптомы и влияние
- Внешняя проба Blackbox (`probe_success`) падает в 0 или мигает.
- Gateway отвечает 502/503, либо запросы к `orders` завершаются ошибкой.
- На дашборде: падает число Ready-реплик, растёт доля 5xx.
- При 2+ репликах влияние кратковременное; при 1 реплике сервис недоступен до перезапуска.

## 2. Диагностика
1. Дашборд «Demo / Overview»: число Ready-реплик, перезапуски, probe_success.
2. PromQL:
   - `kube_deployment_status_replicas_available{namespace="demo"}` — должно совпадать с желаемым числом
   - `increase(kube_pod_container_status_restarts_total{namespace="demo"}[15m])` — рост = CrashLoop
   - `probe_success{instance=~".*gateway.*"}`
3. Причина падения:
   ```bash
   kubectl -n demo get pods -o wide
   kubectl -n demo describe pod <pod>      # Events: OOMKilled, Evicted, ImagePull, Probe failed
   kubectl -n demo logs <pod> --previous   # лог перед падением
   ```
4. Логи в Loki: `{namespace="demo", app="orders"} |= "ERROR"` за момент падения.
5. Если есть активный Chaos-эксперимент: `kubectl get podchaos,networkchaos,stresschaos -A`.

## 3. Автоматическое действие (Remediator)
- Если под просто убит (pod-kill): Kubernetes пересоздаст его сам, Remediator **ничего не делает**, ждёт 2–3 минуты.
- Если CrashLoop / не вернулся в Ready за 3 минуты: `restart` deployment, затем при повторе `rollback`.
- Режим: dry-run по умолчанию; в рабочем режиме нужно подтверждение в Telegram.
- Лимиты: не более 2 действий над одним deployment за 30 минут.
- Журнал: <эндпоинт/лог Remediator>.

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
- Алерт перешёл в resolved, error rate вернулся к норме.

## 6. Откат и риски
- Рестарт при единственной реплике даёт простой на время старта (≈ 30–60 с). Для демо держите ≥ 2 реплики.
- `rollout undo` откатывает на предыдущую ревизию; убедитесь, что она рабочая (`kubectl rollout history`).

## 7. Эскалация
Не восстановилось за 10 минут: связаться с владельцем сервиса; если проблема в узле (`NotReady`, `Evicted`): с отвечающим за инфраструктуру (Ansible/k3s).

## 8. После инцидента
Записать время начала, обнаружения и восстановления (для MTTR); если причина в нехватке ресурсов, пересмотреть requests/limits.

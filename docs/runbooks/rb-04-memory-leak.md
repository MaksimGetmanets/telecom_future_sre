# RB-04: Утечка памяти / OOMKilled

**Алерты:** `DemoMemoryHigh` (warning), `DemoContainerOOMKilled` (critical)
**Затронутый SLO:** availability и latency (косвенно, через рестарты и GC-паузы)
**Владелец:** <кто> · **Последняя проверка:** <дата, `/leak`>

## 1. Симптомы и влияние
- Память пода растёт без возврата к базовому уровню.
- Растут паузы GC, увеличивается латентность.
- В финале контейнер убивается по OOM и перезапускается: кратковременная недоступность.

## 2. Диагностика
1. Дашборд «Demo / JVM»: heap, GC pause, working set памяти по подам.
2. PromQL:
   - `container_memory_working_set_bytes{namespace="demo", container="orders"}` рядом с limit
   - `jvm_memory_used_bytes{area="heap"}` и `rate(jvm_gc_pause_seconds_sum[5m])`
   - `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`
3. Подтверждение причины:
   ```bash
   kubectl -n demo describe pod <pod>    # Last State: Terminated, Reason: OOMKilled
   ```
4. Логи: `{namespace="demo", app="orders"} |= "OutOfMemory"`.
5. Типичная причина в демо: вызов `/leak`.

## 3. Автоматическое действие (Remediator)
- Для `DemoMemoryHigh`: `restart` пода до OOM, чтобы избежать внезапного падения.
- Для `DemoContainerOOMKilled`: Kubernetes уже перезапустил контейнер; Remediator проверяет, что под вернулся в Ready.
- Лимиты: не чаще 1 рестарта за 15 минут на сервис (иначе «лечим симптом по кругу»).
- Режим: dry-run по умолчанию.

## 4. Ручные шаги
```bash
kubectl -n demo rollout restart deploy/orders
# временное смягчение (не решение):
kubectl -n demo set resources deploy/orders --limits=memory=1Gi
```
Если утечка повторяется: снять heap dump до рестарта и передать разработчикам.

## 5. Проверка восстановления
- Память вернулась к базовому уровню и стабильна 15 минут.
- Нет новых OOMKilled.

## 6. Откат и риски
- Рестарт скрывает утечку, но не устраняет её: заведите задачу на исправление.
- Увеличение limit откладывает падение, не решает проблему.

## 7. Эскалация
Повторяется 3 раза подряд: эскалировать разработчикам, рассмотреть откат релиза.

## 8. После инцидента
Записать время до OOM при данной нагрузке; при необходимости подкрутить порог `DemoMemoryHigh`.

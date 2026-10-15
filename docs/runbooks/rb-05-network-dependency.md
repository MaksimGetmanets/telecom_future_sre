# RB-05: Деградация сети / зависимость недоступна

**Алерты:** `SyntheticProbeFailed`, `SyntheticSloBurn`, `DemoHighLatency`, `*LatencyBurn`, `*AvailabilityBurn` · **Severity:** page
**Затронутые SLO:** доступность, latency, синтетическая доступность
**Владелец:** команда проекта (Володин А., Гетманец М.) · **Последняя проверка:** 15.10.2026, Chaos Mesh `orders-network-delay` (1500 мс ± 200, 3 мин) на ВМ

Охватывает связи `gateway → orders` и `orders → PostgreSQL`.

## 1. Симптомы и влияние
- Рост задержек и таймаутов между сервисами, всплеск 5xx/504.
- Внешняя проба Blackbox нестабильна, при этом поды в статусе Ready.
- Если недоступна БД: `orders` отвечает ошибками, gateway проксирует их.
- Замер (задержка 1500 мс на orders): алерт через 37–52 с, проба падала через 11 с, простой по пробам 205 с при длительности сбоя 180 с.

## 2. Диагностика
1. Дашборды «Синтетика: пробы Blackbox» и «Demo Shop: здоровье сервиса и логи» (панели «Соединения с БД (orders)» и «Запросы к БД: пул соединений (orders)»).
2. Что сломалось, сеть или сама БД:
   ```bash
   kubectl -n demo get pods -l app.kubernetes.io/name=postgres
   kubectl get networkchaos -A          # активен ли эксперимент
   kubectl -n demo logs statefulset/postgres --tail=100
   ```
3. PromQL: p95 и доля 5xx для `orders` (см. RB-02, RB-03); метрики пула соединений (`hikaricp_connections_active`, `hikaricp_connections_pending`).
4. Трейс: Grafana → Explore → Tempo, на каком участке (gateway → orders или orders → БД) растёт длительность span'ов или возникают таймауты.
5. Логи: `{namespace="demo", app="orders"} |~ "timeout|Connection refused|could not connect"`.

## 3. Автоматическое действие (remediator)
**Для сетевых проблем автоматика бессильна.** Что происходит на самом деле:
- `SyntheticProbeFailed` и `SyntheticSloBurn` политик не имеют: только уведомление в Telegram.
- Если сработал `DemoHighLatency` или `*AvailabilityBurn`, remediator перезапускает deployment (так было в замерах: `restart` gateway и orders выполнился, но не помог). Задержка Chaos Mesh вешается и на новые поды, поэтому восстановление наступает только с окончанием сбоя.
- Remediator не имеет прав на StatefulSet с PostgreSQL (RBAC только `deployments` и чтение `replicasets` в `demo`).
- Откат и скейл при сетевой проблеме не помогают. Не нажимайте «Выполнить» под такими алертами, пока не выяснили причину.

## 4. Ручные шаги
```bash
# если идёт эксперимент и он не нужен (виды удаляйте отдельными командами):
kubectl -n demo delete networkchaos <name>
# сбросить пул соединений после восстановления сети:
kubectl -n demo rollout restart deploy/orders
# БД: проверить под, логи и диск
kubectl -n demo logs statefulset/postgres --tail=100
```

## 5. Проверка восстановления
- Задержки и ошибки на связях вернулись к норме.
- `probe_success == 1`, пул соединений без очереди ожидания.

## 6. Откат и риски
- Не перезапускать PostgreSQL без понимания причины: риск потери незакоммиченных данных и долгого восстановления.
- Рестарт `orders` кратковременно увеличит ошибки.

## 7. Эскалация
БД недоступна более 5 минут или есть признаки повреждения данных: немедленно эскалировать владельцу БД/инфраструктуры.

## 8. После инцидента
Записать время деградации и восстановления; подумать о таймаутах, retry и circuit breaker на стороне сервиса.

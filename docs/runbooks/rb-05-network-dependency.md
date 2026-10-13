# RB-05: Деградация сети / зависимость недоступна

**Алерты:** `DemoProbeFailed`, `DemoLatencyBurn*`, `DemoErrorRateBurn*`
**Затронутые SLO:** availability, latency p95, error rate
**Владелец:** <кто> · **Последняя проверка:** <дата, Chaos Mesh NetworkChaos>

Охватывает связи `gateway → orders` и `orders → PostgreSQL`.

## 1. Симптомы и влияние
- Рост задержек и таймаутов между сервисами, всплеск 5xx/504.
- Внешняя проба Blackbox нестабильна, при этом поды в статусе Ready.
- Если недоступна БД: `orders` отвечает ошибками, gateway проксирует их.

## 2. Диагностика
1. Дашборд «Demo / Dependencies»: латентность и ошибки по связям, состояние PostgreSQL.
2. Что сломалось, сеть или сама БД:
   ```bash
   kubectl -n demo get pods -l app=postgres
   kubectl -n demo exec deploy/orders -- <проверка соединения с БД / curl orders>
   kubectl get networkchaos -A          # активен ли эксперимент
   ```
3. PromQL: p95 и доля 5xx для `orders` (см. RB-02, RB-03); метрики пула соединений (`hikaricp_connections_active`, `hikaricp_connections_pending`).
4. Трейс: на каком участке (gateway → orders или orders → БД) растёт длительность span'ов или возникают таймауты.
5. Логи: `{namespace="demo", app="orders"} |~ "timeout|Connection refused|could not connect"`.
6. Linkerd (если включён): `linkerd viz stat deploy -n demo`: success rate и latency по связям.

## 3. Автоматическое действие (Remediator)
**Только уведомление в Telegram, без автоматических изменений.**
Причины: рестарт или скейл не лечат сетевые проблемы, а автоматические действия над базой данных слишком рискованны. Remediator не имеет RBAC-прав на StatefulSet с PostgreSQL.
- Допустимо после подтверждения человеком: `restart` `orders`, чтобы сбросить пул соединений.

## 4. Ручные шаги
```bash
# если идёт Chaos-эксперимент и он не нужен:
kubectl -n <chaos-ns> delete networkchaos <name>
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

# Demo-сервисы (apps/)

`gateway → orders → Postgres` на Java 21 и Spring Boot 3.4 (Maven, три модуля: `common`, `gateway`, `orders`).

| Сервис | Что делает |
|---|---|
| `gateway` | Входная точка. `/orders` проксирует в `orders`, статус ответа сохраняется. Если `orders` недоступен, отвечает 502 |
| `orders` | Заказы в Postgres: `GET /orders`, `GET /orders/{id}`, `POST /orders` (`{"item":"book","quantity":2}`) |
| `common` | Ручки сбоев; подключается к обоим сервисам |

## Ручки для имитации сбоев

Есть у обоих сервисов.

| Ручка | Что делает |
|---|---|
| `GET /slow?ms=1500` | Отвечает через заданное время (до 30 с) |
| `GET /fail?p=0.3` | Отвечает HTTP 500 с вероятностью `p` |
| `GET /leak?mb=50` | Удерживает в куче 50 МБ (не освобождаются). `DELETE /leak` очищает |
| `POST /fault?errorRate=0.5&delayMs=300` | **Постоянный** сбой на `/orders`: доля ошибок и задержка. `GET /fault` показывает, `DELETE /fault` сбрасывает |

Состояние хранится в памяти пода, поэтому **перезапуск пода лечит `/fault` и `/leak`**: на этом строится демо самоисцеления
(внести сбой → сработал алерт → remediator перезапустил под → сбой исчез).
Отключается переменной `FAULTS_ENABLED=false` (в прод-режиме ручки не нужны и не защищены, это раздел «Безопасность» в README).

## Метрики и логи (для Dev A)

- Метрики: `/actuator/prometheus`, лейбл `application` (gateway / orders), гистограмма `http_server_requests_seconds_bucket`
  с бакетами 100ms, 300ms, 500ms, 1s, 2s (бакет `le="0.3"` нужен для SLO по p95 < 300 мс).
- SLI считать только по бизнес-ручкам: `uri=~"/orders.*"` (иначе в статистику попадут `/actuator/*`, `/slow`, `/fail`, `/leak`).
  Примеры:
  - доступность: `sum(rate(http_server_requests_seconds_count{application="gateway",uri=~"/orders.*",status!~"5.."}[5m])) / sum(rate(http_server_requests_seconds_count{application="gateway",uri=~"/orders.*"}[5m]))`
  - быстрые запросы (< 300 мс): `sum(rate(http_server_requests_seconds_bucket{application="gateway",uri=~"/orders.*",le="0.3"}[5m])) / sum(rate(http_server_requests_seconds_count{application="gateway",uri=~"/orders.*"}[5m]))`
- ServiceMonitor добавляет лейбл `app_kubernetes_io_name`; все поды в namespace `demo` с лейблами `app.kubernetes.io/name=gateway|orders|postgres`.
- Логи: JSON в stdout (формат logstash), поля `trace_id` и `span_id` подставляет OpenTelemetry agent. Трейсы уходят в `tempo.monitoring.svc:4317` (OTLP gRPC).

## Запуск

В кластере (из корня репозитория):

```bash
make up            # поднимет k3d, соберёт образы, установит стек и demo-сервисы
make apps-reload   # после правок кода: пересобрать образы и перезапустить поды
make apps-test     # тесты в контейнере Maven
```

Проверка:

```bash
kubectl -n demo get pods
kubectl -n demo port-forward svc/gateway 8080:8080
curl -s -X POST localhost:8080/orders -H 'Content-Type: application/json' -d '{"item":"book","quantity":2}'
curl -s localhost:8080/orders
curl -s 'localhost:8080/slow?ms=500'
```

Разработка в IDE без кластера:

```bash
docker run -d --name pg -e POSTGRES_DB=orders -e POSTGRES_USER=orders -e POSTGRES_PASSWORD=orders -p 5432:5432 postgres:16-alpine
PORT=8081 mvn -f apps/pom.xml -pl orders -am spring-boot:run    # orders на :8081
mvn -f apps/pom.xml -pl gateway -am spring-boot:run             # gateway на :8080, ORDERS_URL по умолчанию http://localhost:8081
```

## Известные упрощения демо

- Схема БД создаётся Hibernate (`ddl-auto: update`), миграций нет.
- Пароль Postgres по умолчанию `orders`; на VPS переопределяется через `postgres_password` в Terraform.
- Образы локальные (`gateway:dev`, `orders:dev`), в `ghcr.io` будут публиковаться через GitHub Actions позже.

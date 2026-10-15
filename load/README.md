# Нагрузочные тесты (k6) и замер MTTR

## Что нужно один раз
1. В `terraform/values/kps.yaml` добавить приём remote write (под ключом `prometheus.prometheusSpec`):
   ```yaml
   prometheus:
     prometheusSpec:
       enableRemoteWriteReceiver: true
   ```
   затем `make up` (Prometheus перезапустится).
2. В корневой `Makefile` в конец добавить `include load/load.mk`.
3. `make up` подхватит дашборд `observability/dashboards/k6-capacity.json` («k6: тест вместимости»).

## Запуск
| Команда | Что делает |
|---|---|
| `make load-smoke` | 30 с, 2 пользователя; ненулевой код возврата, если нарушены пороги (ошибки < 1%, p95 < 300 мс) |
| `make load-capacity` | ~9 мин, ступени 10…200 запросов/с, метрики в Prometheus |
| `make mttr SCENARIO=errors RUNS=3` | замер MTTR, результаты дописываются в `docs/results/mttr.csv` |
| `make mttr SCENARIO=latency` | то же для сценария задержки (ожидается действие scale) |

k6 запускается внутри кластера (под в namespace `demo`), поэтому нагрузка идёт на `gateway.demo.svc:8080` без port-forward.

## Как читать результат capacity
На дашборде: ступень, на которой p95 пересекает красную линию 300 мс, и есть предел по SLO. Если растут «пропущенные
итерации», то упёрлись либо сервис, либо сам k6. Записать цифры в `docs/results/` (нагрузка, p95, CPU подов).

## MTTR
`chaos/mttr.py` вносит сбой (`chaos/fault.sh`), ждёт алерт в Prometheus, действие в `/audit` ремедиатора и 5 подряд
успешных проб `GET /orders` быстрее 300 мс. Ремедиатор должен быть в режиме не dry-run, иначе восстановления не будет.
Между прогонами пауза 60 с, а у ремедиатора кулдаун 180 с: при `--runs > 1` для чистых цифр увеличьте `--pause 200`.

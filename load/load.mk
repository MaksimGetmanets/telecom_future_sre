# Цели k6. Подключается строкой `include load/load.mk` в конце корневого Makefile.
# k6 запускается внутри кластера (поды k6 -> gateway.demo.svc), метрики уходят в Prometheus по remote write.
K6_IMAGE ?= grafana/k6:0.54.0
K6_RW_URL ?= http://kps-kube-prometheus-stack-prometheus.monitoring.svc:9090/api/v1/write

load-image: cluster
> docker pull $(K6_IMAGE)
> k3d image import $(K6_IMAGE) -c $(CLUSTER)

# Smoke: 30 секунд, 2 пользователя. Код возврата k6 ненулевой, если пороги нарушены.
load-smoke: load-image
> kubectl -n demo run k6-smoke-$$(date +%s) --rm -i --restart=Never --image=$(K6_IMAGE) --image-pull-policy=IfNotPresent -- run - < load/smoke.js

# Capacity: ~9 минут, до 200 запросов/с. Метрики пишутся в Prometheus (дашборд "k6: тест вместимости").
load-capacity: load-image
> kubectl -n demo run k6-capacity-$$(date +%s) --rm -i --restart=Never --image=$(K6_IMAGE) --image-pull-policy=IfNotPresent \
>   --env=K6_PROMETHEUS_RW_SERVER_URL=$(K6_RW_URL) --env=K6_PROMETHEUS_RW_TREND_STATS='p(95),p(99),avg,max' \
>   --env=K6_PROMETHEUS_RW_PUSH_INTERVAL=5s -- run -o experimental-prometheus-rw - < load/capacity.js

.PHONY: load-image load-smoke load-capacity

# MTTR: внести сбой, замерить обнаружение/действие/восстановление, дописать строку в CSV.
#   make mttr SCENARIO=errors RUNS=3
SCENARIO ?= errors
RUNS ?= 1
mttr:
> python3 chaos/mttr.py $(SCENARIO) --runs $(RUNS) --csv docs/results/mttr.csv

mttr-test:
> python3 -m pytest -q chaos/test_mttr.py

.PHONY: mttr mttr-test

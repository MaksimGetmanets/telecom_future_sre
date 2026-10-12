# Цели для remediator. Подключается строкой `include remediator/remediator.mk` в конце корневого Makefile.
IMAGE_TAG ?= dev

remediator-image: cluster
> docker build -t remediator:$(IMAGE_TAG) remediator
> k3d image import remediator:$(IMAGE_TAG) -c $(CLUSTER)

# После правок кода: пересобрать образ и перезапустить под
remediator-reload: remediator-image
> kubectl -n monitoring rollout restart deploy/remediator
> kubectl -n monitoring rollout status deploy/remediator --timeout=120s

# Юнит-тесты в контейнере (на хосте Python не нужен)
remediator-test:
> docker run --rm -v "$(CURDIR)/remediator:/src:ro" python:3.12-slim \
>   sh -c 'cp -r /src /work && cd /work && pip install -q -r requirements-dev.txt && python -m pytest -q'

# Отправить тестовый алерт в remediator (нужен port-forward: kubectl -n monitoring port-forward svc/remediator 8088:8080)
remediator-fire:
> curl -s -X POST localhost:8088/alert -H 'Content-Type: application/json' \
>   -d '{"alerts":[{"status":"firing","labels":{"alertname":"DemoHighErrorRate","namespace":"demo","deployment":"orders"}}]}'

up: remediator-image

.PHONY: remediator-image remediator-reload remediator-test remediator-fire

# Цели для Telegram-бота. Подключается строкой `include tgbot/tgbot.mk` в корневом Makefile.
TGBOT_TAG ?= dev

tgbot-image: cluster
> docker build -t tgbot:$(TGBOT_TAG) tgbot
> k3d image import tgbot:$(TGBOT_TAG) -c $(CLUSTER)

# После правок кода: пересобрать образ и перезапустить под
tgbot-reload: tgbot-image
> kubectl -n monitoring rollout restart deploy/tgbot
> kubectl -n monitoring rollout status deploy/tgbot --timeout=120s

tgbot-test:
> docker run --rm -v "$(CURDIR)/tgbot:/src:ro" -e GOTOOLCHAIN=auto golang:1.24 \
>   sh -c 'cp -r /src /work && cd /work && go vet ./... && go test ./...'

tgbot-logs:
> kubectl -n monitoring logs deploy/tgbot -f

# Узнать chat id и проверить подключение: написать боту /start, затем смотреть лог (make tgbot-logs)
# Тестовый алерт в бота (порт 8090 локально): kubectl -n monitoring port-forward svc/tgbot 8090:8080 &
tgbot-fire:
> curl -s -X POST localhost:8090/alert -H 'Content-Type: application/json' \
>   -d '{"alerts":[{"status":"firing","labels":{"alertname":"DemoHighErrorRate","namespace":"demo","deployment":"orders","severity":"page"},"annotations":{"description":"тестовый алерт"}}]}'

up: tgbot-image

.PHONY: tgbot-image tgbot-reload tgbot-test tgbot-logs tgbot-fire

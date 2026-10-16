# Telegram-бот

Принимает вебхук Alertmanager (`POST /alert`, порт 8080), дописывает в сообщение ИИ-диагностику от `llm-assistant`
и показывает кнопки подтверждения действий (`restart`, `scale`, `rollback`). Действие выполняет remediator
(`POST /execute`), бот сам ничего не решает. Подробно о сценарии: корневой [README](../README.md), раздел «Telegram-бот».

## В кластере (основной режим)

Бот собирается в образ (`Dockerfile`), разворачивается чартом `chart/` и Terraform (`terraform/tgbot.tf`) вместе со стеком:

```bash
export TF_VAR_telegram_token=<токен от @BotFather>   # необязательно
make up                                              # на ВМ: make deploy DEPLOY_APPS=yes
```

Затем отправьте боту `/start`. Alertmanager шлёт алерты на `http://tgbot.monitoring.svc:8080/alert`, ассистент и remediator
берутся по адресам сервисов в кластере. Один бот = одна реплика (long polling), на хосте второй экземпляр с тем же токеном запускать нельзя.

| Команда | Что делает |
|---|---|
| `/start` (`/start <код>`, если задан `REGISTER_CODE`) | подключить этот чат к алертам, бот ответит chat id |
| `/stop` | отключить чат (закреплённый `TELEGRAM_CHAT_ID` не отключается) |

Режим без Telegram: без токена (или если Telegram недоступен) бот не падает, а пишет алерты и диагностику в лог:
`kubectl -n monitoring logs deploy/tgbot`.

## Локальный запуск и тесты

```bash
cd tgbot && cp .env.example .env     # заполнить токен; .env в git не попадает
go run ./cmd/bot
go vet ./... && go test -race ./...   # или make tgbot-test (в контейнере)
```

Кнопки: данные ограничены 64 байтами (`x|restart|demo|orders|0`), проверяются заново при нажатии, принимаются только из
подключённых чатов и устаревают через 30 минут. Бинарники (`*.bin`) в репозиторий не коммитим.

# LLM-ассистент

Сервис получает алерт, сам собирает контекст (Prometheus, Loki, Kubernetes) и просит OpenAI выдвинуть
гипотезу причины и предложить **одно** действие (OpenAI или Anthropic, на выбор): `restart`, `scale`, `rollback` или `none`.

**Ассистент ничего не выполняет.** Его предложение проходит независимую проверку (`app/schema.py:sanitize`):
действие из белого списка, namespace `demo`, deployment из `ALLOWED_TARGETS` и присутствует в кластере,
для `scale` не больше `MAX_REPLICAS`. Роль в Kubernetes только на чтение. Секреты (Bearer, password=, `sk-…`,
токен Telegram, пароль в JDBC-URL, e-mail) вычищаются из логов до отправки в OpenAI (`app/redact.py`).

## Схема

```
Alertmanager -> remediator /alert -> политика -> действие (как раньше)
                                  \-> фоном: POST llm-assistant /diagnose -> запись event="llm_diagnosis" в аудит (-> Loki)
```

Поле `agrees` в аудите показывает, совпало ли предложение LLM с действием политики. Это материал для демо
и для раздела «ограничения» в отчёте.

## Запуск

```bash
export TF_VAR_anthropic_api_key=sk-ant-... # или TF_VAR_openai_api_key=sk-...; не коммитить
make llm-image
cd terraform && terraform apply -auto-approve -var remediator_dry_run=false
kubectl -n monitoring port-forward svc/llm-assistant 8089:8080 &
make llm-diagnose ALERT=DemoHighErrorRate DEP=orders
```

Без ключа сервис запускается в режиме правил (`model: "rules"`), remediator его не вызывает.
При ошибке OpenAI (сеть, 429, битый JSON) ассистент отвечает по правилам и пишет причину в `fallback_reason`.

## Настройки (env)

| Переменная | По умолчанию |
|---|---|
| `LLM_PROVIDER` | `openai` или `anthropic`; по умолчанию по тому, какой ключ задан |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | пусто, `claude-haiku-5-5` |
| `OPENAI_API_KEY` | пусто (режим правил) |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` (можно любой совместимый) |
| `PROMETHEUS_URL`, `LOKI_URL` | сервисы в `monitoring` |
| `LOKI_SELECTOR` | `{namespace="$namespace", pod=~"$deployment-.*"}` |
| `ALLOWED_TARGETS` | `gateway,orders` |
| `MAX_REPLICAS` | `4` |
| `CACHE_TTL` | `120` с, кэш по fingerprint алерта |
| `DIAGNOSE_TOKEN` | пусто; если задан, нужен `Authorization: Bearer` |

## Промпты

`prompts/system.md` (правила и примеры) и `prompts/user.md` (шаблон с контекстом) лежат в образе:
после правок `make llm-reload`.

## Ограничения

- Метки в Loki (`namespace`, `pod`) зависят от конфига Alloy; если логов нет, поправьте `LOKI_SELECTOR`.
- Метрики приложений ищутся по лейблу `application` (Micrometer); имена задаются в `app/context.py:QUERIES`.
- Тесты используют подменённый HTTP-транспорт: с реальным API OpenAI сервис проверяется вручную (`make llm-diagnose`).

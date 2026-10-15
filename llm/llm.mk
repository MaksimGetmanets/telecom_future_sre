# Цели для LLM-ассистента. Подключается строкой `include llm/llm.mk` в корневом Makefile.
LLM_TAG ?= dev

llm-image: cluster
> docker build -t llm-assistant:$(LLM_TAG) llm
> k3d image import llm-assistant:$(LLM_TAG) -c $(CLUSTER)

# После правок кода или промптов (prompts/ входят в образ)
llm-reload: llm-image
> kubectl -n monitoring rollout restart deploy/llm-assistant
> kubectl -n monitoring rollout status deploy/llm-assistant --timeout=120s

llm-test:
> docker run --rm -v "$(CURDIR)/llm:/src:ro" python:3.12-slim \
>   sh -c 'cp -r /src /work && cd /work && pip install -q -r requirements-dev.txt && python -m pytest -q'

# Ручной диагноз (пока нужен port-forward: kubectl -n monitoring port-forward svc/llm-assistant 8089:8080)
# make llm-diagnose ALERT=DemoHighErrorRate DEP=orders
ALERT ?= DemoHighErrorRate
DEP ?= orders
llm-diagnose:
> curl -s -X POST localhost:8089/diagnose -H 'Content-Type: application/json' \
>   -d '{"labels":{"alertname":"$(ALERT)","namespace":"demo","deployment":"$(DEP)","severity":"critical"}}' | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=2))'

up: llm-image

.PHONY: llm-image llm-reload llm-test llm-diagnose

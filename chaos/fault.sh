#!/usr/bin/env bash
# Внести или снять сбой на ВСЕХ подах сервиса (состояние сбоя хранится в памяти каждого пода).
#   chaos/fault.sh orders 'errorRate=0.5'        # 50% ошибок на /orders
#   chaos/fault.sh orders 'delayMs=600'          # задержка 600 мс
#   chaos/fault.sh orders clear                  # снять
set -euo pipefail
svc=${1:?сервис: orders или gateway}
arg=${2:?параметры сбоя или clear}
for pod in $(kubectl -n demo get pods -l "app.kubernetes.io/name=$svc" -o jsonpath='{.items[*].metadata.name}'); do
  kubectl -n demo port-forward "pod/$pod" 18080:8080 >/dev/null 2>&1 &
  pf=$!
  sleep 1.5
  if [ "$arg" = clear ]; then
    curl -s -m 5 -X DELETE localhost:18080/fault
  else
    curl -s -m 5 -X POST "localhost:18080/fault?$arg"
  fi
  echo "  <- $pod"
  kill "$pf" 2>/dev/null || true
  wait "$pf" 2>/dev/null || true
done

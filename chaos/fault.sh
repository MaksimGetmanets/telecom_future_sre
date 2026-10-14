#!/usr/bin/env bash
# Внести или снять сбой на ВСЕХ подах сервиса (состояние сбоя хранится в памяти каждого пода).
#   chaos/fault.sh orders 'errorRate=0.5'        # 50% ошибок на /orders
#   chaos/fault.sh orders 'delayMs=600'          # задержка 600 мс
#   chaos/fault.sh orders clear                  # снять
# Код возврата 0, если сбой применён ко всем найденным подам; иначе 1 (можно повторить, операция идемпотентна).
set -uo pipefail
svc=${1:?сервис: orders или gateway}
arg=${2:?параметры сбоя или clear}
port=18080
failed=0
pods=$(kubectl -n demo get pods -l "app.kubernetes.io/name=$svc" --field-selector=status.phase=Running \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
[ -n "$pods" ] || { echo "  !! нет запущенных подов $svc" >&2; exit 1; }
for pod in $pods; do
  kubectl -n demo port-forward "pod/$pod" "$port:8080" >/dev/null 2>&1 &
  pf=$!
  ready=0
  for _ in $(seq 1 20); do               # ждём, пока port-forward начнёт отвечать (до 10 с)
    if curl -s -m 2 -o /dev/null "localhost:$port/fault"; then ready=1; break; fi
    sleep 0.5
  done
  ok=0
  if [ "$ready" = 1 ]; then
    if [ "$arg" = clear ]; then
      curl -sf -m 5 -X DELETE "localhost:$port/fault" >/dev/null && ok=1
    else
      curl -sf -m 5 -X POST "localhost:$port/fault?$arg" >/dev/null && ok=1
    fi
  fi
  if [ "$ok" = 1 ]; then echo "  <- $pod"; else echo "  !! $pod: не удалось" >&2; failed=1; fi
  kill "$pf" 2>/dev/null || true
  wait "$pf" 2>/dev/null || true
done
exit $failed

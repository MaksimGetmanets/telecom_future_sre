#!/usr/bin/env python3
"""Замер MTTR: внести сбой, дождаться алерта и действия ремедиатора, дождаться восстановления.

Только стандартная библиотека. Все обращения к кластеру идут через `kubectl` (прокси API-сервера),
порт-форвард не нужен. Сценарии:
  errors   chaos/fault.sh orders errorRate=0.5   (ожидаем DemoHighErrorRate / ErrorBudgetBurn -> restart)
  latency  chaos/fault.sh orders delayMs=600     (ожидаем *Latency* -> scale)

Использование:
  python3 chaos/mttr.py errors --runs 3 --csv docs/results/mttr.csv
  python3 chaos/mttr.py latency --runs 1 --timeout 600

Метки времени: t_inject (сбой внесён), t_detect (алерт firing в Prometheus), t_action (запись в /audit ремедиатора),
t_recover (N подряд успешных проб через gateway). MTTR = t_recover - t_inject.
Если ремедиатор в режиме dry-run, восстановления не будет: прогон закончится по таймауту (recovered=false).
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

ACTION_STATUSES = {"executed", "dry_run", "error"}  # остальные статусы (skipped_*) действием не считаются
CLEAN_PATTERN = "Demo.*"  # SLO-алерты Sloth (окна до 6 ч) гаснут часами, их не ждём: см. --clean-pattern
SCENARIOS = {
    "errors": {"fault": "errorRate=0.5", "alert": "DemoHighErrorRate|.*ErrorBudgetBurn.*"},
    "latency": {"fault": "delayMs=600", "alert": ".*Latency.*"},
}
K6_IMAGE = "grafana/k6:0.54.0"
LOAD_SCRIPT = """import http from 'k6/http';
export const options = { scenarios: { steady: { executor: 'constant-arrival-rate', rate: %d, timeUnit: '1s',
  duration: '30m', preAllocatedVUs: 20, maxVUs: 100 } }, thresholds: {} };
export default function () { http.get('http://gateway.demo.svc:8080/orders'); }
"""
PROM_PROXY = "/api/v1/namespaces/monitoring/services/kps-kube-prometheus-stack-prometheus:9090/proxy"
REM_PROXY = "/api/v1/namespaces/monitoring/services/remediator:8080/proxy"
GATEWAY_PROXY = "/api/v1/namespaces/demo/services/gateway:8080/proxy"


def kubectl_raw(path: str, timeout: float = 10.0) -> tuple[int, str]:
    """GET через API-сервер. Возвращает (код, тело); код 0, если kubectl не смог дойти до сервиса."""
    proc = subprocess.run(["kubectl", "get", "--raw", path], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        return 0, proc.stderr
    return 200, proc.stdout


def probe_gateway(max_latency_s: float) -> bool:
    """Проба: GET /orders через gateway, успех = 200 и быстрее порога."""
    start = time.monotonic()
    try:
        code, _ = kubectl_raw(f"{GATEWAY_PROXY}/orders", timeout=max_latency_s + 5)
    except subprocess.TimeoutExpired:
        return False
    return code == 200 and (time.monotonic() - start) <= max_latency_s


def firing_alerts(pattern: str, namespace_filter: bool = True) -> list[str]:
    ns = 'namespace="demo",' if namespace_filter else ""
    query = f'ALERTS{{alertstate="firing",{ns}alertname=~"{pattern}"}}'
    code, body = kubectl_raw(f"{PROM_PROXY}/api/v1/query?query={urllib.parse.quote(query)}")
    if code != 200:
        return []
    try:
        result = json.loads(body)["data"]["result"]
    except (ValueError, KeyError):
        return []
    return sorted({r["metric"].get("alertname", "") for r in result})


def audit_entries() -> list[dict]:
    code, body = kubectl_raw(f"{REM_PROXY}/audit")
    if code != 200:
        return []
    try:
        data = json.loads(body)
    except ValueError:
        return []
    return data if isinstance(data, list) else data.get("items", [])


def run_fault(service: str, arg: str, attempts: int = 3) -> None:
    """Внести/снять сбой с повторами: поды могут быть в процессе перезапуска, port-forward не сразу готов."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fault.sh")
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(["bash", script, service, arg], capture_output=True, text=True)
        if proc.returncode == 0:
            return
        if attempt == attempts:
            raise RuntimeError(f"fault.sh {service} {arg} не удался: {proc.stderr.strip() or proc.stdout.strip()}")
        time.sleep(5)


def safe_clear(service: str) -> None:
    """Снятие сбоя в конце прогона не должно ронять скрипт: результат уже измерен."""
    try:
        run_fault(service, "clear")
    except RuntimeError as exc:
        print(f"    предупреждение: {exc}", flush=True)


def start_load(rps: int, name: str = "mttr-load"):
    """Фоновая нагрузка внутри кластера (k6): без запросов нет ошибок, и алерт на их долю не может сработать."""
    subprocess.run(["kubectl", "-n", "demo", "delete", "pod", name, "--ignore-not-found", "--wait=true"],
                   capture_output=True, text=True)
    proc = subprocess.Popen(
        ["kubectl", "-n", "demo", "run", name, "-i", "--restart=Never", f"--image={K6_IMAGE}",
         "--image-pull-policy=IfNotPresent", "--", "run", "-"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    proc.stdin.write(LOAD_SCRIPT % rps)
    proc.stdin.close()
    return proc


def stop_load(proc, name: str = "mttr-load") -> None:
    if proc is not None:
        proc.terminate()
    subprocess.run(["kubectl", "-n", "demo", "delete", "pod", name, "--ignore-not-found", "--wait=false"],
                   capture_output=True, text=True)


def get_replicas(service: str) -> int | None:
    proc = subprocess.run(["kubectl", "-n", "demo", "get", "deploy", service, "-o", "jsonpath={.spec.replicas}"],
                          capture_output=True, text=True)
    return int(proc.stdout) if proc.returncode == 0 and proc.stdout.strip().isdigit() else None


def reset_state(service: str, replicas: int | None, clear_timeout: float, log=print, sleep=time.sleep,
                clock=time.time, pattern: str = CLEAN_PATTERN) -> bool:
    """Чистое начальное состояние: прежнее число реплик, сбой снят, нет горящих алертов (иначе замер искажён)."""
    run_fault(service, "clear")
    if replicas is not None and get_replicas(service) != replicas:
        log(f"возвращаю {service} к {replicas} репликам")
        subprocess.run(["kubectl", "-n", "demo", "scale", f"deploy/{service}", f"--replicas={replicas}"],
                       capture_output=True, text=True)
    subprocess.run(["kubectl", "-n", "demo", "rollout", "status", f"deploy/{service}", "--timeout=180s"],
                   capture_output=True, text=True)
    start = clock()
    while clock() - start < clear_timeout:
        names = firing_alerts(pattern, namespace_filter=False)
        if not names:
            return True
        log(f"жду, пока погаснут алерты: {', '.join(names)}")
        sleep(15)
    return False


@dataclass
class Result:
    scenario: str
    run: int
    started: str = ""
    detect_s: float | None = None
    action_s: float | None = None
    mttr_s: float | None = None
    alert: str = ""
    action_status: str = ""
    recovered: bool = False
    notes: list = field(default_factory=list)


def parse_ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def measure(scenario: str, run: int, *, inject, clear, get_alerts, get_audit, probe,
            timeout: float = 600.0, poll: float = 5.0, ok_probes: int = 5,
            clock=time.time, sleep=time.sleep, log=lambda msg: None) -> Result:
    """Один прогон. Все внешние операции передаются функциями, чтобы логику можно было проверить без кластера."""
    res = Result(scenario=scenario, run=run)
    t0 = clock()
    res.started = datetime.fromtimestamp(t0, timezone.utc).isoformat(timespec="seconds")
    inject()
    log("сбой внесён, жду алерт, действие ремедиатора и восстановление")
    consecutive = 0
    last_status = t0
    try:
        while clock() - t0 < timeout:
            now = clock()
            if now - last_status >= 30:
                last_status = now
                log(f"{int(now - t0)} с: алерт={'да' if res.detect_s is not None else 'нет'}, "
                    f"действие={'да' if res.action_s is not None else 'нет'}, успешных проб подряд={consecutive}")
            if res.detect_s is None:
                names = get_alerts()
                if names:
                    res.detect_s = round(now - t0, 1)
                    res.alert = ",".join(names)
                    log(f"{res.detect_s} с: алерт {res.alert} сработал")
            if res.action_s is None:
                for entry in get_audit():
                    try:
                        ts = parse_ts(entry["ts"])
                    except (KeyError, ValueError):
                        continue
                    # ts в аудите с точностью до секунды, поэтому допуск 1 с
                    if ts >= t0 - 1 and str(entry.get("status", "")).startswith("skipped") and entry.get("alertname"):
                        note = f"{entry['status']}: {entry.get('detail', '')}".strip(": ")
                        if note not in res.notes:
                            res.notes.append(note)
                            log(f"ремедиатор пропустил действие ({note})")
                    if ts >= t0 - 1 and entry.get("status") in ACTION_STATUSES:
                        res.action_s = round(max(ts - t0, 0.0), 1)
                        # алерт не мог дойти до ремедиатора раньше, чем сработал: расхождение даёт шаг опроса (около 8 с)
                        if res.detect_s is None or res.detect_s > res.action_s:
                            res.detect_s = res.action_s
                            res.alert = res.alert or entry.get("alertname", "")
                        res.action_status = str(entry.get("status"))
                        log(f"{res.action_s} с: ремедиатор отреагировал ({res.action_status})")
                        break
            # восстановление считаем только после алерта: до него «зелёные» пробы могут быть просто задержкой метрик
            if res.detect_s is not None and probe():
                consecutive += 1
                if consecutive >= ok_probes:
                    res.mttr_s = round(clock() - t0, 1)
                    res.recovered = True
                    log(f"{res.mttr_s} с: восстановление подтверждено")
                    return res
            else:
                consecutive = 0
            sleep(poll)
        res.notes.append("таймаут")
        return res
    finally:
        clear()


def write_csv(path: str, rows: list[Result]) -> None:
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cols = ["scenario", "run", "started", "detect_s", "action_s", "mttr_s", "alert", "action_status", "recovered", "notes"]
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new:
            w.writeheader()
        for r in rows:
            d = asdict(r)
            d["notes"] = "; ".join(d["notes"])
            w.writerow(d)


def summarize(rows: list[Result]) -> str:
    ok = [r.mttr_s for r in rows if r.recovered and r.mttr_s is not None]
    if not ok:
        return "восстановлений нет"
    ok.sort()
    median = ok[len(ok) // 2] if len(ok) % 2 else (ok[len(ok) // 2 - 1] + ok[len(ok) // 2]) / 2
    return f"восстановлено {len(ok)}/{len(rows)}, MTTR мин/медиана/макс = {ok[0]}/{median}/{ok[-1]} с"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenario", choices=sorted(SCENARIOS))
    p.add_argument("--service", default="orders")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timeout", type=float, default=600.0, help="предел одного прогона, с")
    p.add_argument("--max-latency", type=float, default=0.3, help="проба успешна, если ответ быстрее, с")
    p.add_argument("--pause", type=float, default=60.0, help="пауза между прогонами (кулдаун ремедиатора 180 с), с")
    p.add_argument("--rps", type=int, default=20, help="фоновая нагрузка, запросов/с (0 = не запускать, нагрузку дадите сами)")
    p.add_argument("--base-replicas", type=int, default=2, help="исходное число реплик сервиса, к нему возвращаем перед каждым прогоном (0 = взять текущее)")
    p.add_argument("--clean-pattern", default=CLEAN_PATTERN, help="regexp имён алертов, которые должны погаснуть перед прогоном (по умолчанию только Demo*)")
    p.add_argument("--clean-timeout", type=float, default=600.0, help="сколько ждать погасших алертов перед прогоном, с")
    p.add_argument("--csv", default="docs/results/mttr.csv")
    args = p.parse_args(argv)

    sc = SCENARIOS[args.scenario]
    rows = []
    load = None
    if args.rps > 0:
        print(f"Запускаю фоновую нагрузку {args.rps} запросов/с (под mttr-load в namespace demo)...", flush=True)
        load = start_load(args.rps)
        time.sleep(15)  # дать поду стартовать и метрикам появиться
    try:
        rows = run_all(args, sc)
    finally:
        stop_load(load)
    print(summarize(rows))
    print(f"CSV: {args.csv}")
    return 0 if all(r.recovered for r in rows) else 1


def run_all(args, sc) -> list:
    rows = []
    base_replicas = args.base_replicas if args.base_replicas else get_replicas(args.service)
    for i in range(1, args.runs + 1):
        print(f"[{i}/{args.runs}] {args.scenario}: готовлю чистое состояние ({args.service}: {base_replicas} реплик)...", flush=True)
        clean = reset_state(args.service, base_replicas, args.clean_timeout, pattern=args.clean_pattern,
                            log=lambda m: print(f"    {m}", flush=True))
        if not clean:
            print("    ВНИМАНИЕ: алерты не погасли за отведённое время, замер может быть искажён", flush=True)
        print(f"    вношу сбой {sc['fault']} на {args.service}", flush=True)
        res = measure(
            args.scenario, i,
            inject=lambda: run_fault(args.service, sc["fault"]),
            clear=lambda: safe_clear(args.service),
            get_alerts=lambda: firing_alerts(sc["alert"]),
            get_audit=audit_entries,
            probe=lambda: probe_gateway(args.max_latency),
            timeout=args.timeout,
            log=lambda m: print(f"    {m}", flush=True),
        )
        print(f"    алерт через {res.detect_s} с, действие через {res.action_s} с ({res.action_status}), "
              f"MTTR {res.mttr_s} с, recovered={res.recovered}", flush=True)
        rows.append(res)
        write_csv(args.csv, [res])  # сразу после каждого прогона: ни один результат не пропадёт при сбое
        if i < args.runs:
            print(f"    спим {args.pause} s...")
            time.sleep(args.pause)
    return rows


if __name__ == "__main__":
    sys.exit(main())

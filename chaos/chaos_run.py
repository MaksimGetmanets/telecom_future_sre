#!/usr/bin/env python3
"""Замер реакции платформы на сбой, внесённый Chaos Mesh.

Применяет манифест эксперимента и каждые --poll секунд смотрит в Prometheus:
  * detect       - когда впервые загорелся алерт в namespace demo;
  * probe_down   - когда синтетическая проба (probe_success) упала;
  * remediation  - время первой записи remediator в /audit после старта;
  * recovered    - когда алертов нет и пробы снова успешны (подтверждено двумя опросами).
Только stdlib, все запросы идут через `kubectl get --raw` (port-forward не нужен).

  python3 chaos/chaos_run.py chaos/experiments/orders-cpu-stress.yaml --runs 3 --pause 200 \\
      --csv docs/results/chaos-cpu.csv
"""
import argparse
import csv
import datetime
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse

PROM = "/api/v1/namespaces/monitoring/services/kps-kube-prometheus-stack-prometheus:9090/proxy"
AUDIT = "/api/v1/namespaces/monitoring/services/remediator:8080/proxy/audit"


def kubectl(*args, check=True):
    p = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("kubectl %s: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def prom(query):
    path = PROM + "/api/v1/query?query=" + urllib.parse.quote(query)
    data = json.loads(kubectl("get", "--raw", path))
    return data.get("data", {}).get("result", [])


def firing_alerts():
    res = prom('ALERTS{alertstate="firing",namespace="demo"}')
    return {r["metric"].get("alertname", "?") for r in res}


def probe_min():
    res = prom("min(probe_success)")
    if not res:
        return None
    return float(res[0]["value"][1])


def get_audit():
    try:
        data = json.loads(kubectl("get", "--raw", AUDIT))
    except Exception:
        return []
    if isinstance(data, dict):
        for key in ("entries", "items", "audit"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def entry_epoch(entry):
    for key in ("ts", "time", "timestamp", "at"):
        v = entry.get(key) if isinstance(entry, dict) else None
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None


def entry_brief(entry):
    if not isinstance(entry, dict):
        return str(entry)
    parts = [str(entry[k]) for k in ("action", "type", "deployment", "result", "status", "reason") if k in entry]
    return "/".join(parts) or json.dumps(entry, ensure_ascii=False)[:80]


def parse_duration(text):
    if not text:
        return None
    total = 0
    for num, unit in re.findall(r"(\d+)([hms])", str(text)):
        total += int(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total or None


def load_manifest(path):
    out = kubectl("apply", "--dry-run=client", "-o", "json", "-f", path)
    obj = json.loads(out)
    if obj.get("kind") == "List":
        obj = obj["items"][0]
    return obj["kind"], obj["metadata"]["name"], parse_duration(obj.get("spec", {}).get("duration"))


def one_run(path, name, hold, timeout, poll):
    busy = firing_alerts()
    if busy:
        raise SystemExit("Перед стартом уже горят алерты %s. Дождитесь тишины и повторите." % sorted(busy))
    audit_before = len(get_audit())
    t0 = time.time()
    kubectl("apply", "-f", path)
    deleted = False
    detect = probe_down = recovered = chaos_end = None
    candidate = None
    seen = set()
    while time.time() - t0 < timeout:
        time.sleep(poll)
        now = time.time() - t0
        al = firing_alerts()
        pm = probe_min()
        seen |= al
        if al and detect is None:
            detect = now
        if pm is not None and pm < 1 and probe_down is None:
            probe_down = now
        degraded = detect is not None or probe_down is not None
        healthy = not al and (pm is None or pm >= 1)
        if degraded and healthy:
            if candidate is None:
                candidate = now
            else:
                recovered = candidate
                break
        else:
            candidate = None
        if not deleted and now >= hold:
            kubectl("delete", "-f", path, "--ignore-not-found", "--wait=true")
            deleted, chaos_end = True, now
            if not degraded and now >= hold + 60:
                break
        if deleted and not degraded and now >= hold + 60:
            break
    during = None
    if recovered is not None:
        during = chaos_end is None or recovered < chaos_end
    if not deleted:
        kubectl("delete", "-f", path, "--ignore-not-found", "--wait=true", check=False)
    new = get_audit()[audit_before:]
    remed = None
    for e in new:
        ts = entry_epoch(e)
        if ts is not None:
            remed = max(0.0, ts - t0)
            break
    return {
        "detect_s": detect, "probe_down_s": probe_down, "remediation_s": remed,
        "recovered_s": recovered, "recovered_during_chaos": during,
        "alerts": ";".join(sorted(seen)), "audit": ";".join(entry_brief(e) for e in new),
    }


def fmt(v):
    return "-" if v is None else ("%.0f" % v if isinstance(v, float) else str(v))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--pause", type=int, default=200, help="пауза между прогонами, с (больше cooldown remediator 180 с)")
    ap.add_argument("--hold", type=int, help="сколько держать сбой, с (по умолчанию spec.duration, иначе 90)")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--csv")
    a = ap.parse_args()

    kind, name, spec_dur = load_manifest(a.manifest)
    hold = a.hold or spec_dur or 90
    print("Сценарий %s (%s), удержание %d с, прогонов %d" % (name, kind, hold, a.runs))
    ns_ann = kubectl("get", "ns", "demo", "-o", "jsonpath={.metadata.annotations.chaos-mesh\\.org/inject}", check=False)
    if ns_ann.strip() != "enabled":
        print("ВНИМАНИЕ: на namespace demo нет аннотации chaos-mesh.org/inject=enabled, выполните `make chaos-enable`.")

    rows = []
    for i in range(1, a.runs + 1):
        print("\n--- прогон %d/%d ---" % (i, a.runs))
        r = one_run(a.manifest, name, hold, a.timeout, a.poll)
        r.update(scenario=name, run=i, ts=datetime.datetime.now().isoformat(timespec="seconds"))
        rows.append(r)
        print("detect=%s probe_down=%s remediation=%s recovered=%s during_chaos=%s\nalerts=%s\naudit=%s" % (
            fmt(r["detect_s"]), fmt(r["probe_down_s"]), fmt(r["remediation_s"]), fmt(r["recovered_s"]),
            r["recovered_during_chaos"], r["alerts"] or "-", r["audit"] or "-"))
        if i < a.runs:
            print("пауза %d с" % a.pause)
            time.sleep(a.pause)

    if a.csv:
        new = not os.path.exists(a.csv)
        with open(a.csv, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "scenario", "run", "detect_s", "probe_down_s", "remediation_s",
                            "recovered_s", "recovered_during_chaos", "alerts", "audit"])
            for r in rows:
                w.writerow([r["ts"], r["scenario"], r["run"], fmt(r["detect_s"]), fmt(r["probe_down_s"]),
                            fmt(r["remediation_s"]), fmt(r["recovered_s"]), r["recovered_during_chaos"],
                            r["alerts"], r["audit"]])
        print("\nCSV дописан: %s" % a.csv)

    for key in ("detect_s", "probe_down_s", "recovered_s"):
        vals = [r[key] for r in rows if r[key] is not None]
        if vals:
            print("%s: медиана %.0f с (n=%d)" % (key, statistics.median(vals), len(vals)))


if __name__ == "__main__":
    sys.exit(main())

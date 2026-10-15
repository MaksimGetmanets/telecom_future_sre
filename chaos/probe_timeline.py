#!/usr/bin/env python3
"""Фактические интервалы недоступности по probe_success (min по сервисам) за окно.

Использование (время в UTC, как в CSV chaos-*.csv; ts строки = конец прогона):
  python3 chaos/probe_timeline.py 2026-10-15T17:40:00 2026-10-15T17:52:09
Печатает каждый интервал, где min(probe_success) < 1, и его длительность.
Это и есть реальное время недоступности сервиса (без задержки закрытия алертов).
"""
import datetime, json, subprocess, sys, urllib.parse

PROM = "/api/v1/namespaces/monitoring/services/kps-kube-prometheus-stack-prometheus:9090/proxy"
STEP = 5


def ts(s):
    return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp()


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    start, end = ts(sys.argv[1]), ts(sys.argv[2])
    q = "min(probe_success)"
    path = "%s/api/v1/query_range?query=%s&start=%d&end=%d&step=%d" % (
        PROM, urllib.parse.quote(q), start, end, STEP)
    out = subprocess.run(["kubectl", "get", "--raw", path], capture_output=True, text=True, check=True).stdout
    res = json.loads(out)["data"]["result"]
    if not res:
        sys.exit("нет данных за окно")
    pts = [(float(t), float(v)) for t, v in res[0]["values"]]
    down_from = None
    n = 0
    for t, v in pts:
        if v < 1 and down_from is None:
            down_from = t
        if v >= 1 and down_from is not None:
            n += 1
            print("недоступность #%d: %s .. %s UTC, %d с" % (
                n, datetime.datetime.utcfromtimestamp(down_from).strftime("%H:%M:%S"),
                datetime.datetime.utcfromtimestamp(t).strftime("%H:%M:%S"), t - down_from))
            down_from = None
    if down_from is not None:
        print("недоступность не закончилась к концу окна (с %s UTC)" %
              datetime.datetime.utcfromtimestamp(down_from).strftime("%H:%M:%S"))
    if n == 0 and down_from is None:
        print("за окно сервис не падал (probe_success=1 везде)")


main()

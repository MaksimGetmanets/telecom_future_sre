"""Проверка логики замера MTTR на подставных функциях (кластер не нужен). Запуск: pytest chaos/test_mttr.py"""
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import mttr  # noqa: E402


class FakeTime:
    def __init__(self):
        self.t = 1_000_000.0

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def run(alert_at, action_at, healthy_at, timeout=300.0):
    ft = FakeTime()
    start = ft.t
    calls = {"inject": 0, "clear": 0}

    def inject():
        calls["inject"] += 1

    def clear():
        calls["clear"] += 1

    res = mttr.measure(
        "errors", 1,
        inject=inject, clear=clear,
        get_alerts=lambda: ["DemoHighErrorRate"] if ft.t - start >= alert_at else [],
        get_audit=lambda: [{"ts": iso(start + action_at), "status": "executed"}] if ft.t - start >= action_at else [],
        probe=lambda: ft.t - start >= healthy_at,
        timeout=timeout, poll=5, ok_probes=3, clock=ft.clock, sleep=ft.sleep,
    )
    return res, calls


def test_full_cycle_measures_all_stages():
    res, calls = run(alert_at=40, action_at=45, healthy_at=70)
    assert res.recovered
    assert res.detect_s == 40
    assert res.action_s == 45
    assert res.action_status == "executed"
    assert 80 <= res.mttr_s <= 90  # здоровье с 70 с + 3 успешные пробы с шагом 5 с
    assert calls == {"inject": 1, "clear": 1}


def test_probe_green_before_alert_does_not_count_as_recovery():
    res, _ = run(alert_at=100, action_at=105, healthy_at=0)
    assert res.recovered
    assert res.mttr_s >= 100


def test_timeout_without_recovery_still_clears_fault():
    res, calls = run(alert_at=10, action_at=15, healthy_at=10_000, timeout=60)
    assert not res.recovered
    assert res.mttr_s is None
    assert "таймаут" in res.notes
    assert calls["clear"] == 1


def test_ignored_audit_entries_are_not_actions():
    ft = FakeTime()
    start = ft.t
    res = mttr.measure(
        "errors", 1, inject=lambda: None, clear=lambda: None,
        get_alerts=lambda: ["X"],
        get_audit=lambda: [{"ts": iso(start + 1), "status": "skipped_guard"}],
        probe=lambda: False, timeout=30, poll=5, clock=ft.clock, sleep=ft.sleep,
    )
    assert res.action_s is None


def test_csv_and_summary(tmp_path):
    rows = [mttr.Result("errors", 1, mttr_s=60.0, recovered=True), mttr.Result("errors", 2, mttr_s=100.0, recovered=True),
            mttr.Result("errors", 3)]
    path = tmp_path / "out" / "mttr.csv"
    mttr.write_csv(str(path), rows)
    mttr.write_csv(str(path), rows[:1])  # дозапись без повторного заголовка
    data = list(csv.DictReader(open(path, encoding="utf-8")))
    assert len(data) == 4
    assert data[0]["scenario"] == "errors"
    assert "2/3" in mttr.summarize(rows)
    assert "80.0" in mttr.summarize(rows)


def test_action_before_polled_alert_clamps_detect_and_skipped_is_noted():
    ft = FakeTime()
    start = ft.t
    logs = []
    res = mttr.measure(
        "latency", 1, inject=lambda: None, clear=lambda: None,
        get_alerts=lambda: ["DemoHighLatency"] if ft.t - start >= 50 else [],
        get_audit=lambda: [
            {"ts": iso(start + 40), "status": "skipped_at_max", "detail": "уже 4 реплик", "alertname": "X"},
            {"ts": iso(start + 45), "status": "executed", "alertname": "DemoHighLatency"},
        ],
        probe=lambda: True, timeout=200, poll=5, ok_probes=2, clock=ft.clock, sleep=ft.sleep, log=logs.append,
    )
    assert res.action_s == 45
    assert res.detect_s == 45  # опрос увидел алерт позже действия: берём время действия
    assert any("skipped_at_max" in n for n in res.notes)

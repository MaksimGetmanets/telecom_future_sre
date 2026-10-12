"""Аудит: каждое решение — одна JSON-строка в stdout (подхватывает Alloy -> Loki) и кольцевой буфер для GET /audit."""
import json
import logging
import sys
from collections import deque
from datetime import datetime, timezone

_logger = logging.getLogger("remediator.audit")
if not _logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

_recent: deque = deque(maxlen=200)


def record(**fields) -> dict:
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": "remediation", **fields}
    _recent.append(entry)
    _logger.info(json.dumps(entry, ensure_ascii=False))
    return entry


def recent(limit: int = 50) -> list[dict]:
    return list(_recent)[-limit:][::-1]

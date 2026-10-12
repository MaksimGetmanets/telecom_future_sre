"""Предохранители: пауза между действиями и лимит в час на один deployment."""
import threading
import time
from collections import defaultdict, deque
from typing import Callable


class Guard:
    def __init__(self, cooldown_seconds: int, max_per_hour: int, clock: Callable[[], float] = time.time):
        self.cooldown = cooldown_seconds
        self.max_per_hour = max_per_hour
        self.clock = clock
        self._lock = threading.Lock()
        self._last: dict[tuple, float] = {}
        self._hourly: dict[tuple, deque] = defaultdict(deque)

    def check_and_record(self, namespace: str, deployment: str, action: str) -> str | None:
        """Возвращает причину отказа или None (тогда действие учтено и его можно выполнять)."""
        key = (namespace, deployment, action)
        dep_key = (namespace, deployment)
        now = self.clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.cooldown:
                return f"cooldown: прошло {int(now - last)} с из {self.cooldown}"
            window = self._hourly[dep_key]
            while window and now - window[0] > 3600:
                window.popleft()
            if len(window) >= self.max_per_hour:
                return f"rate_limit: {self.max_per_hour} действий в час на {namespace}/{deployment}"
            self._last[key] = now
            window.append(now)
            return None

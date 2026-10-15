"""Вычистка секретов из текста, который уходит во внешний LLM."""
import re

_PATTERNS = [
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED]"),  # токен Telegram-бота
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization)\b(\s*[=:]\s*)\S+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+@"), r"\1[REDACTED]@"),  # jdbc:postgresql://user:pass@host
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
]


def redact(text: str, max_len: int = 400) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text if len(text) <= max_len else text[:max_len] + "…"

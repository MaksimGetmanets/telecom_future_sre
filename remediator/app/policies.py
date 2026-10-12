"""Таблица политик: какой алерт -> какое действие.

Действие в самом алерте не передаётся (так договорились с Dev A), решает remediator.
Значения в `match` — регулярные выражения, сравнение по полному совпадению.
"""
import re
from dataclasses import dataclass, field

import yaml

ACTIONS = ("restart", "scale")


@dataclass(frozen=True)
class Policy:
    name: str
    match: dict[str, str]
    action: str
    params: dict = field(default_factory=dict)

    def matches(self, labels: dict[str, str]) -> bool:
        return all(re.fullmatch(pattern, labels.get(key, "")) for key, pattern in self.match.items())


@dataclass(frozen=True)
class Defaults:
    cooldown_seconds: int = 180
    max_actions_per_hour: int = 6
    allowed_namespaces: tuple[str, ...] = ("demo",)


@dataclass(frozen=True)
class PolicySet:
    defaults: Defaults
    policies: tuple[Policy, ...]

    def find(self, labels: dict[str, str]) -> Policy | None:
        for policy in self.policies:
            if policy.matches(labels):
                return policy
        return None


def parse(data: dict) -> PolicySet:
    raw_defaults = data.get("defaults") or {}
    defaults = Defaults(
        cooldown_seconds=int(raw_defaults.get("cooldown_seconds", Defaults.cooldown_seconds)),
        max_actions_per_hour=int(raw_defaults.get("max_actions_per_hour", Defaults.max_actions_per_hour)),
        allowed_namespaces=tuple(raw_defaults.get("allowed_namespaces", Defaults.allowed_namespaces)),
    )
    policies = []
    for i, item in enumerate(data.get("policies") or []):
        action = item.get("action")
        if action not in ACTIONS:
            raise ValueError(f"policies[{i}]: action должен быть одним из {ACTIONS}, получено {action!r}")
        match = item.get("match") or {}
        if not match:
            raise ValueError(f"policies[{i}]: пустой match сработал бы на любой алерт")
        for pattern in match.values():
            re.compile(pattern)
        policies.append(
            Policy(
                name=item.get("name", f"policy-{i}"),
                match={k: str(v) for k, v in match.items()},
                action=action,
                params=item.get("params") or {},
            )
        )
    return PolicySet(defaults=defaults, policies=tuple(policies))


def load(path: str) -> PolicySet:
    with open(path, encoding="utf-8") as f:
        return parse(yaml.safe_load(f) or {})

"""Формат ответа ассистента и независимая от LLM проверка предложенного действия."""
from typing import Any

ACTIONS = ("restart", "scale", "rollback", "none")

# JSON-схема для OpenAI structured outputs (strict)
RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "diagnosis",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["hypothesis", "confidence", "evidence", "action", "deployment", "replicas"],
        "properties": {
            "hypothesis": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "action": {"type": "string", "enum": list(ACTIONS)},
            "deployment": {"type": "string"},
            "replicas": {"type": "integer"},
        },
    },
}


def sanitize(raw: dict, *, namespace: str, allowed_namespaces: list[str],
             allowed_targets: list[str], known_deployments: list[str],
             current_replicas: dict[str, int], max_replicas: int) -> dict:
    """Приводит ответ LLM к безопасному виду. LLM никогда ничего не выполняет,
    а предложение проходит через белый список: действие, namespace, deployment, лимит реплик."""
    hypothesis = str(raw.get("hypothesis", "")).strip()[:600]
    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    evidence = [str(e).strip()[:300] for e in (raw.get("evidence") or []) if str(e).strip()][:6]

    action = str(raw.get("action", "none")).strip().lower()
    deployment = str(raw.get("deployment", "")).strip()
    try:
        replicas = int(raw.get("replicas", 0))
    except (TypeError, ValueError):
        replicas = 0

    suggested: dict[str, Any] = {"type": action, "deployment": deployment}
    rejected = None

    if action not in ACTIONS:
        rejected = f"действие '{action}' не из белого списка"
        action = "none"
    elif action != "none":
        if namespace not in allowed_namespaces:
            rejected = f"namespace '{namespace}' не разрешён"
        elif deployment not in allowed_targets:
            rejected = f"deployment '{deployment}' не разрешён"
        elif deployment not in known_deployments:
            rejected = f"deployment '{deployment}' не найден в контексте"
        elif action == "scale":
            cur = current_replicas.get(deployment, 1)
            if replicas <= cur:
                replicas = cur + 1
            if replicas > max_replicas:
                rejected = f"{replicas} реплик больше лимита {max_replicas}"
            else:
                suggested["replicas"] = replicas
        elif action == "rollback" and deployment == "":
            rejected = "не указан deployment"
    if rejected:
        suggested = {"type": "none", "deployment": deployment}
    return {
        "hypothesis": hypothesis,
        "confidence": round(confidence, 2),
        "evidence": evidence,
        "suggested_action": suggested,
        "validated": rejected is None,
        "rejected_reason": rejected,
    }

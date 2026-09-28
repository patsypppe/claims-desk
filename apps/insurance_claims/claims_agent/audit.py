"""Audit events and PII masking. Event details are masked BEFORE they are constructed."""
from typing import Any, Literal

from claims_agent.domain.models import FrozenModel

AuditKind = Literal["transition", "tool_called", "tool_blocked", "tool_failed", "validator_reject",
                    "fallback_used", "llm_value_rejected", "injection_flagged", "escalated", "consent",
                    "pii_captured", "llm_degraded"]


def _mask_word(word: str) -> str:
    return word[:1] + "*" * (len(word) - 1) if word else word


def mask(field: str, value: str) -> str:
    """Mask a PII value for logs/UI. Never reversible, keeps just enough for a human to recognise."""
    if not value:
        return ""
    if field == "name":
        return " ".join(_mask_word(w) for w in value.split())
    if field == "dob":
        return f"****-**-{value[-2:]}"
    if field == "phone":
        return f"***-***-{value[-4:]}"
    if field == "email":
        local, _, domain = value.partition("@")
        return f"{_mask_word(local)}@{domain}" if domain else _mask_word(value)
    if field == "id_last4":
        return f"**{value[-2:]}"
    return "***"


class AuditEvent(FrozenModel):
    kind: AuditKind
    detail: dict[str, Any]
    turn: int

    @classmethod
    def pii_captured(cls, *, field: str, value: str, turn: int) -> "AuditEvent":
        return cls(kind="pii_captured", detail={"field": field, "masked": mask(field, value)}, turn=turn)

    @classmethod
    def tool(cls, *, kind: AuditKind, tool: str, phase: str, consent: str, turn: int,
             reason: str | None = None) -> "AuditEvent":
        detail = {"tool": tool, "phase": phase, "consent": consent}
        if reason:
            detail["reason"] = reason
        return cls(kind=kind, detail=detail, turn=turn)

    @classmethod
    def transition(cls, *, from_phase: str, to_phase: str, turn: int, cause: str) -> "AuditEvent":
        return cls(kind="transition", detail={"from": from_phase, "to": to_phase, "cause": cause}, turn=turn)

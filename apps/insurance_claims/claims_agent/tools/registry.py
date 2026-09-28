"""Phase-gated tool registry. Every tool call — from the controller or an LLM request — goes through here.

Authorization is enforced in this layer, never by prompting: a forbidden call fails even if asked for.
Identity-scoping arguments (party_id, recipient address, ...) are never accepted from callers; tools
derive them from authoritative state.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from claims_agent.audit import AuditEvent
from claims_agent.domain.models import FrozenModel
from claims_agent.grounding.facts import Fact
from claims_agent.state import ConsentState, ConversationState, Phase

P = Phase
PERMISSIONS: dict[str, frozenset[Phase]] = {
    "verify_identity": frozenset({P.VERIFY_ID}),
    "send_otp": frozenset({P.VERIFY_ID}),
    "verify_otp": frozenset({P.VERIFY_ID}),
    "request_representative_consent": frozenset({P.VERIFY_ID}),
    "search_claims": frozenset({P.RESOLVE_INTENT, P.PROCESS_CASE}),
    "get_claim_details": frozenset({P.PROCESS_CASE}),
    "get_followup_guidance": frozenset({P.PROCESS_CASE}),
    "get_document_guidance": frozenset({P.PROCESS_CASE}),
    "build_summary": frozenset({P.POST_PROCESS}),
    "send_summary_email": frozenset({P.POST_PROCESS}),
    "escalate_to_human": frozenset({P.VERIFY_ID, P.RESOLVE_INTENT, P.PROCESS_CASE, P.POST_PROCESS}),
}
FORBIDDEN_ARGS = frozenset({"party_id", "to", "email", "recipient", "verified", "phase", "consent"})


class ToolResult(FrozenModel):
    ok: bool
    facts: tuple[Fact, ...] = ()
    data: dict[str, Any] = {}
    error: str | None = None


class ToolFailure(RuntimeError):
    """A permitted tool could not complete (downstream failure). Mapped to a tool_failed event."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


Guard = Callable[[ConversationState], str | None]
ToolFn = Callable[..., ToolResult]


def require_verified(state: ConversationState) -> str | None:
    return None if state.verification.verified and state.verification.party_id else "not_verified"


def require_selected_case(state: ConversationState) -> str | None:
    return require_verified(state) or (None if state.selected_case_id else "no_selected_case")


def require_email_consent(state: ConversationState) -> str | None:
    if reason := require_verified(state):
        return reason
    if state.consent != ConsentState.GRANTED:
        return "consent_not_granted"
    return "already_sent" if state.email_sent else None


def require_not_escalated(state: ConversationState) -> str | None:
    return "already_escalated" if state.escalation.active else None


def require_unverified(state: ConversationState) -> str | None:
    return "already_verified" if state.verification.verified else None


def require_third_party(state: ConversationState) -> str | None:
    return None if state.speaker.role == "third_party" else "not_third_party"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: ToolFn
    guard: Guard | None = None


@dataclass
class ToolRegistry:
    repo: Any
    clock: Any
    verifier: Any
    email_sender: Any
    handoff: Any
    consent_service: Any
    otp: Any = None
    enforce_permissions: bool = True
    specs: dict[str, ToolSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from claims_agent.tools.impl import default_specs

        for spec in default_specs():
            self.specs[spec.name] = spec

    def is_permitted(self, tool: str, phase: Phase) -> bool:
        if not self.enforce_permissions:
            return tool in PERMISSIONS
        return phase in PERMISSIONS.get(tool, frozenset())

    def _block_reason(self, name: str, state: ConversationState) -> str | None:
        if name not in self.specs or name not in PERMISSIONS:
            return "unknown_tool"
        if not self.is_permitted(name, state.phase):
            return f"not_permitted_in_{state.phase.value}"
        guard = self.specs[name].guard
        return guard(state) if (guard and self.enforce_permissions) else None

    def call(self, name: str, state: ConversationState, **args: Any) -> tuple[ToolResult, AuditEvent]:
        ignored = sorted(k for k in args if k in FORBIDDEN_ARGS)
        clean = {k: v for k, v in args.items() if k not in FORBIDDEN_ARGS}
        common = {"tool": name, "phase": state.phase.value, "consent": state.consent.value, "turn": state.turn}
        reason = self._block_reason(name, state)
        if reason:
            event = AuditEvent.tool(kind="tool_blocked", reason=reason, **common)
            return ToolResult(ok=False, error=reason), _with_ignored(event, ignored)
        try:
            result = self.specs[name].fn(self, state, **clean)
        except ToolFailure as failure:
            event = AuditEvent.tool(kind="tool_failed", reason=failure.code, **common)
            return ToolResult(ok=False, error=failure.code), _with_ignored(event, ignored)
        event = AuditEvent.tool(kind="tool_called", **common)
        return result, _with_ignored(event, ignored)


def _with_ignored(event: AuditEvent, ignored: list[str]) -> AuditEvent:
    if not ignored:
        return event
    return event.model_copy(update={"detail": {**event.detail, "ignored_args": ignored}})

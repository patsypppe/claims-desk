"""Deterministic SOP controller. Owns phase, transitions, counters, tool calls and escalation.

The LLM's analysis is advisory input; only tool results and application logic change authoritative state.
"""
from enum import StrEnum
from typing import Any

from claims_agent.audit import AuditEvent
from claims_agent.config import Settings
from claims_agent.domain.models import FrozenModel
from claims_agent.domain.repository import FixtureRepository
from claims_agent.extraction.schema import TurnAnalysis
from claims_agent.grounding.facts import Fact
from claims_agent.intent import CaseOption
from claims_agent.policy.emotion import NEUTRAL, EmotionStrategy
from claims_agent.state import ConversationState, Phase
from claims_agent.tools.registry import ToolRegistry, ToolResult


class ControllerAction(StrEnum):
    ASK_FIELDS = "ASK_FIELDS"
    OFFER_ALT_FIELD = "OFFER_ALT_FIELD"
    VERIFY_FAILED = "VERIFY_FAILED"
    CONFIRM_CONFLICT = "CONFIRM_CONFLICT"
    REP_CONSENT_PENDING = "REP_CONSENT_PENDING"
    REFUSE_THIRD_PARTY = "REFUSE_THIRD_PARTY"
    ASK_INTENT = "ASK_INTENT"
    DISAMBIGUATE_CASE = "DISAMBIGUATE_CASE"
    NO_MATCHING_CASE = "NO_MATCHING_CASE"
    NO_CLAIMS = "NO_CLAIMS"
    PRESENT_CASE = "PRESENT_CASE"
    ANSWER = "ANSWER"
    NOT_IN_DATA = "NOT_IN_DATA"
    OFFER_EMAIL = "OFFER_EMAIL"
    CLARIFY_CONSENT = "CLARIFY_CONSENT"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_FAILED = "EMAIL_FAILED"
    EMAIL_SKIPPED = "EMAIL_SKIPPED"
    REDIRECT_SCOPE = "REDIRECT_SCOPE"
    REFUSE_UNSAFE = "REFUSE_UNSAFE"
    ESCALATE = "ESCALATE"
    ESCALATED_HOLD = "ESCALATED_HOLD"
    CLOSE = "CLOSE"


class Decision(FrozenModel):
    state: ConversationState
    action: ControllerAction
    facts: tuple[Fact, ...] = ()
    alternatives: tuple[str, ...] = ()
    options: tuple[CaseOption, ...] = ()
    details: dict[str, Any] = {}
    emotion: EmotionStrategy = NEUTRAL
    events: tuple[AuditEvent, ...] = ()


class StepContext:
    """Per-turn accumulator for audit events (local to one step; state itself stays immutable)."""

    def __init__(self, ctl: "WorkflowController", analysis: TurnAnalysis, text: str, conflicts: list[str]) -> None:
        self.ctl, self.analysis, self.text, self.conflicts = ctl, analysis, text, conflicts
        self.events: list[AuditEvent] = []
        self.emotion: EmotionStrategy = NEUTRAL
        self.option_facts: tuple[Fact, ...] = ()

    def call(self, tool: str, state: ConversationState, **args) -> ToolResult:
        result, event = self.ctl.registry.call(tool, state, **args)
        self.events.append(event)
        return result

    def transition(self, state: ConversationState, to: Phase, cause: str) -> ConversationState:
        self.events.append(AuditEvent.transition(from_phase=state.phase.value, to_phase=to.value,
                                                 turn=state.turn, cause=cause))
        return state.model_copy(update={"phase": to})

    def decide(self, state: ConversationState, action: ControllerAction, **kw) -> Decision:
        details = kw.get("details") or {}
        offers_human = details.get("offer_human") or self.emotion.offer_human or details.get("implicit_offer")
        if offers_human and state.phase not in (Phase.ESCALATED, Phase.COMPLETE, Phase.POST_PROCESS):
            reason = details.get("offer_reason") or details.get("implicit_offer") or "caller_request"
            state = state.model_copy(update={"pending_human_offer": reason})
        return Decision(state=state, action=action, emotion=self.emotion, events=tuple(self.events), **kw)

    def consent_event(self, state: ConversationState, outcome: str) -> AuditEvent:
        return AuditEvent(kind="consent", detail={"outcome": outcome, "offer_id": state.offer_id}, turn=state.turn)

    def escalate(self, state: ConversationState, reason: str) -> Decision:
        result = self.call("escalate_to_human", state, reason=reason)
        if not result.ok:
            return self.decide(state, ControllerAction.ESCALATED_HOLD)
        escalation = state.escalation.model_copy(update={"active": True, "reason": reason,
                                                         "ticket_id": result.data["ticket_id"]})
        state = self.transition(state.model_copy(update={"escalation": escalation, "expected_field": None}),
                                Phase.ESCALATED, reason)
        self.events.append(AuditEvent(kind="escalated", detail={"reason": reason}, turn=state.turn))
        return self.decide(state, ControllerAction.ESCALATE, facts=result.facts, details={"reason": reason})


class WorkflowController:
    def __init__(self, *, repo: FixtureRepository, registry: ToolRegistry, settings: Settings, clock,
                 lockouts=None) -> None:
        self.repo, self.registry, self.settings, self.clock = repo, registry, settings, clock
        self.lockouts = lockouts

    def record_verification_failure(self, candidate_party_id: str | None) -> None:
        if self.lockouts is not None and candidate_party_id:
            self.lockouts.record_failure(candidate_party_id)

    def is_locked_out(self, party_id: str | None) -> bool:
        if self.lockouts is None or not party_id:
            return False
        return self.lockouts.is_locked(party_id, self.settings.lockout_failures)

    def step(self, state: ConversationState, analysis: TurnAnalysis, text: str,
             conflicts: list[str] | None = None) -> Decision:
        from claims_agent.phases import dispatch

        ctx = StepContext(self, analysis, text, conflicts or [])
        return dispatch.run(ctx, state)

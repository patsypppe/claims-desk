"""Authoritative conversation state. Immutable: every change produces a new object."""
from enum import StrEnum
from typing import Literal

from claims_agent.domain.models import FrozenModel

PiiField = Literal["name", "dob", "phone", "email", "id_last4"]
PII_FIELDS: tuple[PiiField, ...] = ("name", "dob", "phone", "email", "id_last4")


class Phase(StrEnum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    COMPLETE = "COMPLETE"
    ESCALATED = "ESCALATED"


class ConsentState(StrEnum):
    NOT_OFFERED = "NOT_OFFERED"
    OFFERED = "OFFERED"
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"
    SENT = "SENT"
    FAILED = "FAILED"


class ObservedValue(FrozenModel):
    field: PiiField
    normalized: str
    masked: str
    turn: int
    source: Literal["rules", "llm"]
    superseded: bool = False


class IntentHints(FrozenModel):
    case_type: Literal["healthcare", "dental", "auto"] | None = None
    status: Literal["denied", "closed", "open"] | None = None
    month: int | None = None
    year: int | None = None
    claim_id: str | None = None
    topic: str | None = None


class LookupHints(FrozenModel):
    policy_number: str | None = None


class Counters(FrozenModel):
    failed_verifications: int = 0
    refusals: int = 0
    out_of_scope: int = 0
    clarifications: int = 0
    doc_alternatives_given: int = 0
    consent_clarifications: int = 0
    email_failures: int = 0
    heated_turns: int = 0


class Verification(FrozenModel):
    verified: bool = False
    party_id: str | None = None
    method: Literal["self", "representative"] | None = None


class Speaker(FrozenModel):
    role: Literal["self", "third_party", "unknown"] = "unknown"
    rep_name: str | None = None
    relationship: str | None = None        # caller's relation TO the policyholder ("son"), when stated
    subject_relation: str | None = None    # policyholder's relation to the caller ("my mother" -> "mother")


class Escalation(FrozenModel):
    active: bool = False
    reason: str | None = None
    ticket_id: str | None = None


class ConversationState(FrozenModel):
    session_id: str
    phase: Phase = Phase.VERIFY_ID
    turn: int = 0
    observed: tuple[ObservedValue, ...] = ()
    refused: frozenset[PiiField] = frozenset()
    lookup: LookupHints = LookupHints()
    intent: IntentHints = IntentHints()
    verification: Verification = Verification()
    speaker: Speaker = Speaker()
    selected_case_id: str | None = None
    candidate_case_ids: tuple[str, ...] = ()
    counters: Counters = Counters()
    consent: ConsentState = ConsentState.NOT_OFFERED
    offer_id: str | None = None
    email_sent: bool = False
    escalation: Escalation = Escalation()
    expected_field: PiiField | None = None
    awaiting_anything_else: bool = False
    last_verification_key: str | None = None
    pending_human_offer: str | None = None
    disclosed_fact_ids: tuple[str, ...] = ()
    degraded: bool = False

    def current(self, field: PiiField) -> ObservedValue | None:
        live = [o for o in self.observed if o.field == field and not o.superseded]
        return live[-1] if live else None

    def current_values(self) -> dict[str, str]:
        return {f: o.normalized for f in PII_FIELDS if (o := self.current(f))}


class StateSnapshot(FrozenModel):
    """Masked, UI/eval-safe view of the state. Never includes raw PII or pre-verification party ids."""
    phase: Phase
    verified: bool
    verified_party_id: str | None
    verification_method: str | None
    captured_fields: dict[str, str]
    captured_count: int
    refused_fields: tuple[str, ...]
    intent_hints: dict
    selected_case_id: str | None
    candidate_case_ids: tuple[str, ...]
    counters: dict
    consent: ConsentState
    escalated: bool
    escalation_reason: str | None
    escalation_ticket: str | None
    expected_field: str | None
    degraded: bool


def snapshot(state: ConversationState) -> StateSnapshot:
    captured = {f: o.masked for f in PII_FIELDS if (o := state.current(f))}
    verified = state.verification.verified
    return StateSnapshot(
        phase=state.phase, verified=verified,
        verified_party_id=state.verification.party_id if verified else None,
        verification_method=state.verification.method if verified else None,
        captured_fields=captured, captured_count=len(captured),
        refused_fields=tuple(sorted(state.refused)),
        intent_hints=state.intent.model_dump(exclude_none=True),
        selected_case_id=state.selected_case_id if verified else None,
        candidate_case_ids=state.candidate_case_ids if verified else (),
        counters=state.counters.model_dump(), consent=state.consent,
        escalated=state.escalation.active, escalation_reason=state.escalation.reason,
        escalation_ticket=state.escalation.ticket_id,
        expected_field=state.expected_field, degraded=state.degraded,
    )

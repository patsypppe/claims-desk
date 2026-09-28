"""VERIFY_ID: the hard gate. Only a verify_identity tool result can mark the caller verified."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.phases import resolve
from claims_agent.state import ConversationState, Phase, Verification
from claims_agent.verification import MIN_FACTORS

ASK_ORDER = ("name", "dob", "id_last4", "phone", "email")


def askable(state: ConversationState) -> list[str]:
    have = state.current_values()
    return [f for f in ASK_ORDER if f not in have and f not in state.refused]


def protected_request(ctx: StepContext) -> bool:
    intent = ctx.analysis.intent
    return bool(intent.topic != "none" or intent.asked_attribute != "none" or intent.claim_id or intent.status)


def factor_key(state: ConversationState) -> str:
    items = sorted(state.current_values().items())
    return "|".join(f"{k}={v}" for k, v in items) + f"|policy={state.lookup.policy_number}"


def _verified(ctx: StepContext, state: ConversationState, party_id: str) -> Decision:
    state = state.model_copy(update={"verification": Verification(verified=True, party_id=party_id, method="self"),
                                     "expected_field": None})
    state = ctx.transition(state, Phase.RESOLVE_INTENT, "identity_verified")
    return resolve.handle(ctx, state, just_verified=True)


def failed(ctx: StepContext, state: ConversationState, candidate: str | None) -> Decision:
    failed = state.counters.failed_verifications + 1
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"failed_verifications": failed}),
                                     "expected_field": None})
    ctx.ctl.record_verification_failure(candidate)
    if failed >= ctx.ctl.settings.max_verification_attempts:
        return ctx.escalate(state, "verification_failed")
    alternatives = tuple(f for f in ASK_ORDER if f not in state.refused)
    remaining = ctx.ctl.settings.max_verification_attempts - failed
    return ctx.decide(state, A.VERIFY_FAILED, alternatives=alternatives, details={"attempts_left": remaining})


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    if state.speaker.role == "third_party":
        from claims_agent.phases import representative

        return representative.handle(ctx, state)
    if ctx.conflicts:
        state = state.model_copy(update={"expected_field": ctx.conflicts[0]})
        return ctx.decide(state, A.CONFIRM_CONFLICT, details={"field": ctx.conflicts[0]})
    factors = state.current_values()
    key = factor_key(state)
    if len(factors) >= MIN_FACTORS and key != state.last_verification_key:
        state = state.model_copy(update={"last_verification_key": key})
        result = ctx.call("verify_identity", state)
        if result.ok and ctx.ctl.is_locked_out(result.data["party_id"]):
            return failed(ctx, state, result.data["party_id"])  # same reply as any mismatch: no oracle
        if result.ok:
            return _verified(ctx, state, result.data["party_id"])
        if result.data.get("status") == "failed":
            # A policy-number typo with otherwise-matching PII is not evidence of an attack on the record.
            lockout_key = None if result.data.get("internal_reason") == "policy_mismatch" else \
                result.data.get("candidate_party_id")
            return failed(ctx, state, lockout_key)
    remaining = askable(state)
    if len(factors) + len(remaining) < MIN_FACTORS:
        return ctx.escalate(state, "insufficient_verification_factors")
    if not remaining:  # every field supplied or refused and the set already failed: ask to re-confirm
        alternatives = tuple(f for f in ASK_ORDER if f not in state.refused)
        return ctx.decide(state.model_copy(update={"expected_field": None}), A.VERIFY_FAILED,
                          alternatives=alternatives, details={"attempts_left": None})
    refused_now = [c.field for c in ctx.analysis.pii_candidates if c.caller_refused]
    state = state.model_copy(update={"expected_field": remaining[0] if remaining else None})
    action = A.OFFER_ALT_FIELD if refused_now else A.ASK_FIELDS
    details = {"captured": len(factors), "needed": max(0, MIN_FACTORS - len(factors)),
               "protected_request": protected_request(ctx), "refused": refused_now}
    return ctx.decide(state, action, alternatives=tuple(remaining), details=details)

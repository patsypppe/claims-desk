"""Third-party callers: only a LISTED representative, with the policyholder's ≥3 factors AND the
policyholder's out-of-band approval, may proceed. Everyone else gets a generic refusal."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.phases import resolve, verify
from claims_agent.representatives import listed_representative
from claims_agent.state import ConversationState, Phase, Verification
from claims_agent.verification import MIN_FACTORS


def _refuse(ctx: StepContext, state: ConversationState) -> Decision:
    return ctx.decide(state.model_copy(update={"expected_field": None}), A.REFUSE_THIRD_PARTY,
                      details={"offer_human": True})


def _approved(ctx: StepContext, state: ConversationState, party_id: str) -> Decision:
    verification = Verification(verified=True, party_id=party_id, method="representative")
    state = state.model_copy(update={"verification": verification, "expected_field": None})
    verify.record_verification(ctx, state)
    state = ctx.transition(state, Phase.RESOLVE_INTENT, "representative_authorized")
    return resolve.handle(ctx, state, just_verified=True, representative=True)


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    if listed_representative(ctx.ctl.repo, state.speaker) is None:
        return _refuse(ctx, state)
    factors = state.current_values()
    key = verify.factor_key(state)
    if len(factors) >= MIN_FACTORS and key != state.last_verification_key:
        state = state.model_copy(update={"last_verification_key": key})
        result = ctx.call("request_representative_consent", state)
        if result.ok and ctx.ctl.is_locked_out(result.data["party_id"]):
            return verify.failed(ctx, state, result.data["party_id"])
        if result.ok:
            return _approved(ctx, state, result.data["party_id"])
        if result.data.get("status") in ("timeout", "denied"):
            return ctx.escalate(state, "representative_consent_timeout")
        return verify.failed(ctx, state, result.data.get("candidate_party_id"))
    remaining = verify.askable(state)
    if len(factors) + len(remaining) < MIN_FACTORS:
        return ctx.escalate(state, "insufficient_verification_factors")
    if not remaining:
        return ctx.decide(state.model_copy(update={"expected_field": None}), A.VERIFY_FAILED,
                          alternatives=tuple(f for f in verify.ASK_ORDER if f not in state.refused))
    state = state.model_copy(update={"expected_field": remaining[0] if remaining else None})
    details = {"captured": len(factors), "for_policyholder": True, "protected_request": False}
    return ctx.decide(state, A.ASK_FIELDS, alternatives=tuple(remaining), details=details)

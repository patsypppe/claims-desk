"""VERIFY_ID: the hard gate. Only a verify_identity tool result can mark the caller verified."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.phases import resolve
import re
import time

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


OTP_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _verified(ctx: StepContext, state: ConversationState, party_id: str, method: str = "self") -> Decision:
    state = state.model_copy(update={"verification": Verification(verified=True, party_id=party_id, method=method),
                                     "expected_field": None, "otp_pending": False})
    record_verification(ctx, state)
    state = ctx.transition(state, Phase.RESOLVE_INTENT, "identity_verified")
    return resolve.handle(ctx, state, just_verified=True)


def record_verification(ctx: StepContext, state: ConversationState) -> None:
    """Documentation of how identity (and any representative authority) was established."""
    from claims_agent.audit import AuditEvent

    detail = {"method": state.verification.method, "factors": sorted(state.current_values()),
              "party_id": state.verification.party_id}
    if state.verification.method == "representative":
        detail["representative"] = {"name": state.speaker.rep_name, "relationship": state.speaker.relationship}
    ctx.events.append(AuditEvent(kind="verification_record", detail=detail, turn=state.turn))


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


def _send_otp(ctx: StepContext, state: ConversationState) -> Decision:
    ctx.call("send_otp", state)
    state = state.model_copy(update={"otp_pending": True, "expected_field": "otp"})
    return ctx.decide(state, A.OTP_SENT)


def _otp_turn(ctx: StepContext, state: ConversationState) -> Decision:
    match = OTP_CODE_RE.search(ctx.text)
    if not match:
        return ctx.decide(state, A.OTP_REMIND)
    started = time.monotonic()
    result = ctx.call("verify_otp", state, code=match.group(1))
    ctx.ctl.pad_verification(started)
    status = result.data.get("status")
    if result.ok and not ctx.ctl.is_locked_out(result.data["party_id"]):
        return _verified(ctx, state, result.data["party_id"], method="otp")
    if status == "wrong":
        return ctx.decide(state, A.OTP_WRONG)
    state = state.model_copy(update={"otp_pending": False})
    return failed(ctx, state, None)


def _otp_policy_applies(ctx: StepContext, state: ConversationState, refused_now: list[str]) -> bool:
    policy = ctx.ctl.settings.verification_policy
    have = len(state.current_values())
    if policy == "knowledge_plus_otp":
        return have >= 2
    if policy == "any3_or_otp":  # possession factor only when knowledge factors can no longer reach 3
        return have >= 2 and have + len(askable(state)) < MIN_FACTORS
    return False


def _channel(ctx: StepContext, state: ConversationState) -> Decision | None:
    token, state_cleared = state.channel_token, state.model_copy(update={"channel_token": None})
    result = ctx.call("accept_channel_assertion", state, token=token)
    return _verified(ctx, state_cleared, result.data["party_id"], method="channel") if result.ok else None


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    if state.channel_token:
        decision = _channel(ctx, state)
        if decision is not None:
            return decision
        state = state.model_copy(update={"channel_token": None})
    if state.otp_pending:
        return _otp_turn(ctx, state)
    if state.speaker.role == "third_party":
        from claims_agent.phases import representative

        return representative.handle(ctx, state)
    if ctx.conflicts:
        state = state.model_copy(update={"expected_field": ctx.conflicts[0]})
        return ctx.decide(state, A.CONFIRM_CONFLICT, details={"field": ctx.conflicts[0]})
    factors = state.current_values()
    refused_now = [c.field for c in ctx.analysis.pii_candidates if c.caller_refused]
    if _otp_policy_applies(ctx, state, refused_now):
        return _send_otp(ctx, state)
    key = factor_key(state)
    if len(factors) >= MIN_FACTORS and key != state.last_verification_key:
        state = state.model_copy(update={"last_verification_key": key})
        started = time.monotonic()
        result = ctx.call("verify_identity", state)
        ctx.ctl.pad_verification(started)
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
    state = state.model_copy(update={"expected_field": remaining[0] if remaining else None})
    action = A.OFFER_ALT_FIELD if refused_now else A.ASK_FIELDS
    details = {"captured": len(factors), "needed": max(0, MIN_FACTORS - len(factors)),
               "protected_request": protected_request(ctx), "refused": refused_now}
    return ctx.decide(state, action, alternatives=tuple(remaining), details=details)

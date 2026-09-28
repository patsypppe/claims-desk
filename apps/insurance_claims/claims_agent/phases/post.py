"""POST_PROCESS: optional email summary. Offering is not consent; only an explicit yes sends, once, on file."""
import uuid

from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.state import ConsentState, ConversationState, Phase

MAX_CONSENT_CLARIFICATIONS = 2
MAX_SEND_ATTEMPTS = 2


def enter(ctx: StepContext, state: ConversationState) -> Decision:
    state = ctx.transition(state, Phase.POST_PROCESS, "case_handled")
    summary = ctx.call("build_summary", state)
    state = state.model_copy(update={"consent": ConsentState.OFFERED, "offer_id": uuid.uuid4().hex[:8],
                                     "awaiting_anything_else": False})
    return ctx.decide(state, A.OFFER_EMAIL, facts=summary.facts)


def _complete(ctx: StepContext, state: ConversationState, action: A, **kw) -> Decision:
    state = ctx.transition(state, Phase.COMPLETE, action.value.lower())
    return ctx.decide(state, action, **kw)


def _send(ctx: StepContext, state: ConversationState) -> Decision:
    state = state.model_copy(update={"consent": ConsentState.GRANTED})
    ctx.events.append(ctx.consent_event(state, "granted"))
    summary = ctx.call("build_summary", state)
    result = ctx.call("send_summary_email", state, subject=summary.data.get("subject", ""),
                      body=summary.data.get("body", ""))
    if result.ok:
        state = state.model_copy(update={"consent": ConsentState.SENT, "email_sent": True})
        return _complete(ctx, state, A.EMAIL_SENT, facts=result.facts)
    failures = state.counters.email_failures + 1
    state = state.model_copy(update={"consent": ConsentState.FAILED,
                                     "counters": state.counters.model_copy(update={"email_failures": failures})})
    if failures >= MAX_SEND_ATTEMPTS:
        return _complete(ctx, state, A.EMAIL_FAILED, details={"final": True})
    return ctx.decide(state, A.EMAIL_FAILED, details={"final": False})


def _skip(ctx: StepContext, state: ConversationState, reason: str) -> Decision:
    state = state.model_copy(update={"consent": ConsentState.DECLINED})
    ctx.events.append(ctx.consent_event(state, reason))
    return _complete(ctx, state, A.EMAIL_SKIPPED, details={"reason": reason})


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    analysis = ctx.analysis
    if analysis.requested_action == "request_other_email":
        return ctx.decide(state, A.OFFER_EMAIL, details={"other_address_refused": True})
    signal = analysis.consent_signal
    if signal == "YES":
        return _send(ctx, state)
    if signal == "NO" or analysis.requested_action == "done":
        return _skip(ctx, state, "declined")
    count = state.counters.consent_clarifications + 1
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"consent_clarifications": count})})
    if count >= MAX_CONSENT_CLARIFICATIONS:
        return _skip(ctx, state, "no_clear_consent")
    return ctx.decide(state, A.CLARIFY_CONSENT)

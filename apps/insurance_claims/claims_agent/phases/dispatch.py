"""Top-level per-turn dispatch: global guards first, then the current phase's handler."""
from claims_agent.audit import AuditEvent
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.phases import post, process, resolve, verify
from claims_agent.policy.emotion import HEATED, strategy_for
from claims_agent.policy.scope import decide_scope
from claims_agent.state import ConversationState, Phase

HANDLERS = {
    Phase.VERIFY_ID: verify.handle,
    Phase.RESOLVE_INTENT: resolve.handle,
    Phase.PROCESS_CASE: process.handle,
    Phase.POST_PROCESS: post.handle,
}


def _guard_tool_requests(ctx: StepContext, state: ConversationState) -> None:
    """LLM/caller tool requests never execute directly; forbidden ones are recorded as blocked attempts."""
    for request in ctx.analysis.tool_requests:
        if not ctx.ctl.registry.is_permitted(request.name, state.phase):
            ctx.call(request.name, state)


def run(ctx: StepContext, state: ConversationState) -> Decision:
    analysis = ctx.analysis
    if analysis.injection_suspected:
        ctx.events.append(AuditEvent(kind="injection_flagged", detail={"phase": state.phase.value}, turn=state.turn))
    heated = state.counters.heated_turns + (1 if analysis.emotion.label in HEATED else 0)
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"heated_turns": heated})})
    ctx.emotion = strategy_for(analysis.emotion.label, analysis.emotion.intensity, heated)
    if state.phase == Phase.ESCALATED:
        return ctx.decide(state, A.ESCALATED_HOLD)
    if state.phase == Phase.COMPLETE:
        return ctx.decide(state, A.CLOSE)
    _guard_tool_requests(ctx, state)
    offer, state = state.pending_human_offer, state.model_copy(update={"pending_human_offer": None})
    if analysis.requested_action == "request_human":
        return ctx.escalate(state, "caller_request")
    if offer and analysis.consent_signal == "YES" and analysis.requested_action != "ask_question":
        return ctx.escalate(state, offer)
    scoped = _scope(ctx, state)
    return scoped if scoped is not None else HANDLERS[state.phase](ctx, state)


def _scope(ctx: StepContext, state: ConversationState) -> Decision | None:
    settings = ctx.ctl.settings
    decision = decide_scope(ctx.analysis, ctx.text, state, settings.oos_offer_threshold,
                            settings.oos_escalation_threshold)
    if decision is None:
        return None
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"out_of_scope": decision.count})})
    if decision.kind == "escalate":
        return ctx.escalate(state, "repeated_out_of_scope")
    action = A.REFUSE_UNSAFE if decision.kind == "refuse_unsafe" else A.REDIRECT_SCOPE
    details = {"count": decision.count, "offer_human": decision.offer_human, "resume_field": state.expected_field}
    return ctx.decide(state, action, details=details)

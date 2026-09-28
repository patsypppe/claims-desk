"""Top-level per-turn dispatch: global guards first, then the current phase's handler."""
from claims_agent.audit import AuditEvent
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.grounding.facts import Fact
from claims_agent.phases import post, process, resolve, verify
from claims_agent.policy.emotion import HEATED, EmotionStrategy, strategy_for

MANIPULATION = EmotionStrategy(label="manipulation", steps=("explain_requirement", "return_to_action"))
THREAT = EmotionStrategy(label="threat", intensity="high", steps=("set_boundary", "explain_requirement",
                                                                   "return_to_action"), offer_human=True)
from claims_agent.policy.scope import decide_scope
from claims_agent.state import ConsentState, ConversationState, IntentHints, Phase

# Side-effecting tools (escalation, consent requests, email) can only be invoked by the controller's own flow.
REQUESTABLE_TOOLS = frozenset({"search_claims", "get_claim_details", "get_followup_guidance", "get_document_guidance"})
SENT_FACT = Fact(fact_id="tool.send_summary_email.result", label="email_sent", value="sent",
                 display="summary already emailed")
HANDLERS = {
    Phase.VERIFY_ID: verify.handle,
    Phase.RESOLVE_INTENT: resolve.handle,
    Phase.PROCESS_CASE: process.handle,
    Phase.POST_PROCESS: post.handle,
}


def _guard_tool_requests(ctx: StepContext, state: ConversationState) -> None:
    """LLM/caller tool requests go through the permission guard like any other call.

    Permitted requests run (identity scope still comes from state; results are not disclosed unless the
    controller's own flow uses them); forbidden ones are blocked and audited.
    """
    for request in ctx.analysis.tool_requests:
        if request.name not in REQUESTABLE_TOOLS:
            ctx.events.append(AuditEvent.tool(kind="tool_blocked", tool=request.name, phase=state.phase.value,
                                              consent=state.consent.value, turn=state.turn,
                                              reason="not_requestable_by_model"))
            continue
        args = {k: v for k, v in (("case_id", request.case_id), ("document", request.document)) if v}
        ctx.call(request.name, state, **args)


def run(ctx: StepContext, state: ConversationState) -> Decision:
    analysis = ctx.analysis
    if analysis.injection_suspected or analysis.social_engineering:
        ctx.events.append(AuditEvent(kind="injection_flagged", detail={"phase": state.phase.value}, turn=state.turn))
        attempts = state.counters.manipulation_attempts + 1
        state = state.model_copy(update={"counters": state.counters.model_copy(
            update={"manipulation_attempts": attempts})})
    heated = state.counters.heated_turns + (1 if analysis.emotion.label in HEATED else 0)
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"heated_turns": heated})})
    previous_emotion = state.last_emotion
    state = state.model_copy(update={"last_emotion": analysis.emotion.label})
    ctx.emotion = strategy_for(analysis.emotion.label, analysis.emotion.intensity, heated,
                               already_acknowledged=previous_emotion == analysis.emotion.label)
    if analysis.social_engineering and not state.verification.verified:
        ctx.emotion = MANIPULATION  # neutral: restate the requirement, no "fair question" pleasantries
    if analysis.threat:
        ctx.emotion = THREAT
    if analysis.wellbeing_risk:  # people before process: care + crisis resources + a human, in any phase
        if state.escalation.active:
            return ctx.decide(state, A.CRISIS_SUPPORT)
        return ctx.escalate(state, "wellbeing_concern")
    if state.phase == Phase.ESCALATED:
        return ctx.decide(state, A.ESCALATED_HOLD)
    if state.phase == Phase.COMPLETE:
        retract = state.email_sent and analysis.consent_signal == "NO"
        facts = (SENT_FACT,) if retract else ()
        return ctx.decide(state, A.CLOSE, details={"already_sent": retract}, facts=facts)
    _guard_tool_requests(ctx, state)
    offer, state = state.pending_human_offer, state.model_copy(update={"pending_human_offer": None})
    if analysis.requested_action == "request_human":
        return ctx.escalate(state, "caller_request")
    if offer and analysis.consent_signal == "YES" and analysis.requested_action != "ask_question":
        return ctx.escalate(state, offer)
    if analysis.requested_action == "readback":
        return ctx.decide(state, A.REFUSE_READBACK, details={"resume_field": state.expected_field})
    if analysis.requested_action == "start_over":
        return _start_over(ctx, state)
    scoped = _scope(ctx, state)
    return scoped if scoped is not None else HANDLERS[state.phase](ctx, state)


def _start_over(ctx: StepContext, state: ConversationState) -> Decision:
    """Keep what must persist (verification, counters, refusals); clear the conversational thread."""
    ctx.restarted = True
    ctx.events.append(AuditEvent(kind="repair", detail={"pattern": "start_over"}, turn=state.turn))
    if not state.verification.verified:
        state = state.model_copy(update={"observed": (), "last_verification_key": None, "expected_field": None,
                                         "intent": IntentHints(), "otp_pending": False})
        return verify.handle(ctx, state)
    state = state.model_copy(update={"intent": IntentHints(), "selected_case_id": None, "candidate_case_ids": (),
                                     "awaiting_anything_else": False, "consent": ConsentState.NOT_OFFERED,
                                     "offer_id": None})
    if state.phase != Phase.RESOLVE_INTENT:
        state = ctx.transition(state, Phase.RESOLVE_INTENT, "caller_start_over")
    return resolve.handle(ctx, state)


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

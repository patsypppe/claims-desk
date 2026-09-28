"""PROCESS_CASE: grounded answers about the selected claim only."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.state import ConversationState, Phase


def present(ctx: StepContext, state: ConversationState, unmatched: tuple[str, ...] = (),
            extra: dict | None = None) -> Decision:
    result = ctx.call("get_claim_details", state)
    if not result.ok:
        return ctx.escalate(state, "tool_failure")
    state = state.model_copy(update={"awaiting_anything_else": True})
    details = {"unmatched": list(unmatched), "topic": state.intent.topic, **(extra or {})}
    if deadline_passed(result.facts):
        details["implicit_offer"] = "deadline_review"   # the deadline text offers a representative
    return ctx.decide(state, A.PRESENT_CASE, facts=result.facts, details=details)


def deadline_passed(facts) -> bool:
    return any(f.label == "appeal_deadline_status" and f.value == "passed" for f in facts)


def _switching_claim(ctx: StepContext, state: ConversationState) -> bool:
    intent = ctx.analysis.intent
    selected = ctx.ctl.repo.claim(state.selected_case_id)
    if intent.claim_id and intent.claim_id != state.selected_case_id:
        return True
    return bool(intent.case_type and selected and intent.case_type != selected.case_type)


def _is_done(ctx: StepContext, state: ConversationState) -> bool:
    a = ctx.analysis
    return a.requested_action == "done" or (
        state.awaiting_anything_else and a.consent_signal == "NO" and a.requested_action != "ask_question")


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    from claims_agent.phases import post, resolve

    if _is_done(ctx, state):
        return post.enter(ctx, state)
    if _switching_claim(ctx, state):
        from claims_agent.phases.resolve import turn_hints

        state = state.model_copy(update={"selected_case_id": None, "candidate_case_ids": (),
                                         "awaiting_anything_else": False, "intent": turn_hints(ctx)})
        state = ctx.transition(state, Phase.RESOLVE_INTENT, "caller_switched_claim")
        return resolve.handle(ctx, state)
    result = ctx.call("get_claim_details", state)
    if not result.ok:
        return ctx.escalate(state, "tool_failure")
    from claims_agent.phases.answers import answer

    return answer(ctx, state.model_copy(update={"awaiting_anything_else": True}), result.facts)

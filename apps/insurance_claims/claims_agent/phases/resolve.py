"""RESOLVE_INTENT: map remembered hints onto the verified caller's own claims."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.intent import option_for, pick_option, resolve
from claims_agent.state import ConversationState, IntentHints, Phase


def turn_hints(ctx: StepContext) -> IntentHints:
    i = ctx.analysis.intent
    return IntentHints(case_type=i.case_type, status=i.status, month=i.month, year=i.year, claim_id=i.claim_id)


def select(ctx: StepContext, state: ConversationState, case_id: str, unmatched: tuple[str, ...] = ()) -> Decision:
    from claims_agent.phases import process

    state = state.model_copy(update={"selected_case_id": case_id, "candidate_case_ids": ()})
    state = ctx.transition(state, Phase.PROCESS_CASE, "case_selected")
    return process.present(ctx, state, unmatched)


def _clarify(ctx: StepContext, state: ConversationState, options) -> Decision:
    count = state.counters.clarifications + 1
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"clarifications": count})})
    if count >= ctx.ctl.settings.max_clarifications:
        return ctx.escalate(state, "unresolved_ambiguity")
    return ctx.decide(state, A.DISAMBIGUATE_CASE, options=tuple(options), details={"repeat": True},
                      facts=ctx.option_facts)


def handle(ctx: StepContext, state: ConversationState, just_verified: bool = False) -> Decision:
    result = ctx.call("search_claims", state)
    if not result.ok:
        return ctx.escalate(state, "tool_failure")
    case_ids = set(result.data["case_ids"])
    claims = tuple(c for c in ctx.ctl.repo.claims_for(state.verification.party_id) if c.case_id in case_ids)
    ctx.option_facts = result.facts
    details = {"just_verified": just_verified}
    if state.candidate_case_ids and not just_verified:
        options = tuple(option_for(c) for c in claims if c.case_id in state.candidate_case_ids)
        picked = pick_option(options, turn_hints(ctx), ctx.text)
        return select(ctx, state, picked) if picked else _clarify(ctx, state, options)
    if ctx.analysis.requested_action == "done" and not just_verified:
        from claims_agent.phases import post

        return post.enter(ctx, state)
    res = resolve(claims, state.intent)
    if res.action == "PRESENT_CASE":
        return select(ctx, state, res.case_id, res.unmatched)
    if res.action == "DISAMBIGUATE_CASE":
        state = state.model_copy(update={"candidate_case_ids": res.candidates})
        return ctx.decide(state, A.DISAMBIGUATE_CASE, options=res.options, details=details, facts=result.facts)
    if res.action == "NO_MATCHING_CASE":
        state = state.model_copy(update={"intent": state.intent.model_copy(update={"claim_id": None})})
        return ctx.decide(state, A.NO_MATCHING_CASE, options=res.options, details=details, facts=result.facts)
    if res.action == "NO_CLAIMS":
        return ctx.decide(state.model_copy(update={"awaiting_anything_else": True}), A.NO_CLAIMS, details=details)
    return ctx.decide(state, A.ASK_INTENT, options=res.options, details=details, facts=result.facts)

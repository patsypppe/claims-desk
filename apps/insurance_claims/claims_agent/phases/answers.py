"""Chooses WHICH grounded facts answer the caller's question. Every answer is a list of fact ids."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.grounding.facts import Fact, not_in_data_fact, payout_facts
from claims_agent.state import ConversationState

NOT_IN_DATA_ATTRS = ("provider_or_facility", "payment_date")
DEADLINE_TOPICS = ("document_submission", "next_steps", "appeal_question")


def _by_label(facts: tuple[Fact, ...], *labels: str) -> list[Fact]:
    return [f for f in facts if f.label in labels]


def _doc_unavailable(ctx: StepContext, state: ConversationState, claim_facts) -> Decision:
    count = state.counters.doc_alternatives_given + 1
    state = state.model_copy(update={"counters": state.counters.model_copy(update={"doc_alternatives_given": count})})
    exhausted = count >= 2
    if exhausted:
        result = ctx.call("get_followup_guidance", state, topic="document_submission", text=ctx.text,
                          document_unavailable=True)
    else:
        result = ctx.call("get_document_guidance", state, document=ctx.analysis.intent.documents_mentioned[0],
                          unavailable=True)
    facts = claim_facts + result.facts
    return ctx.decide(state, A.ANSWER, facts=facts,
                      details={"answer_ids": [f.fact_id for f in result.facts], "offer_human": exhausted,
                               "offer_reason": "document_alternatives_exhausted"})


def _guidance(ctx: StepContext, state: ConversationState, claim_facts, deadline: list[Fact]) -> list[Fact]:
    intent = ctx.analysis.intent
    result = ctx.call("get_followup_guidance", state, topic=intent.topic, text=ctx.text,
                      followup_topic=intent.followup_topic)
    if result.ok and result.data.get("topic") != "fallback":
        fresh = deadline and deadline[0].fact_id not in state.disclosed_fact_ids  # don't repeat the caveat
        extra = deadline if intent.topic in DEADLINE_TOPICS and fresh and deadline[0].value == "passed" else []
        return list(result.facts) + extra
    if intent.documents_mentioned:
        doc = ctx.call("get_document_guidance", state, document=intent.documents_mentioned[0])
        return list(doc.facts)
    return list(result.facts) if result.ok else []


def answer(ctx: StepContext, state: ConversationState, claim_facts: tuple[Fact, ...]) -> Decision:
    intent = ctx.analysis.intent
    claim = ctx.ctl.repo.claim(state.selected_case_id)
    deadline = _by_label(claim_facts, "appeal_deadline_status")
    if intent.asked_attribute in NOT_IN_DATA_ATTRS:
        fact = not_in_data_fact(claim, intent.asked_attribute)
        return ctx.decide(state, A.NOT_IN_DATA, facts=claim_facts + (fact,),
                          details={"answer_ids": [fact.fact_id], "offer_human": False})
    if intent.document_unavailable and intent.documents_mentioned:
        return _doc_unavailable(ctx, state, claim_facts)
    chosen: list[Fact]
    if intent.asked_attribute == "denial_reason" or intent.topic == "denial_question":
        chosen = _by_label(claim_facts, "denial_reason", "document_needed") or _by_label(claim_facts, "status")
    elif intent.asked_attribute == "amounts" or intent.topic == "payment_question":
        chosen = list(payout_facts(claim, ctx.ctl.repo.claim_schema))
    elif intent.asked_attribute == "deadline" or intent.topic == "appeal_question":
        chosen = deadline + _by_label(claim_facts, "document_needed") or _by_label(claim_facts, "status")
    elif intent.asked_attribute == "status" or intent.topic == "status_inquiry":
        chosen = _by_label(claim_facts, "status", "denial_reason")
    else:
        chosen = _guidance(ctx, state, claim_facts, deadline) or _by_label(claim_facts, "status")
    extra = tuple(f for f in chosen if f not in claim_facts)
    details = {"answer_ids": [f.fact_id for f in chosen], "offer_human": False}
    if any(f.label == "appeal_deadline_status" and f.value == "passed" for f in chosen):
        details["implicit_offer"] = "deadline_review"
        if intent.asked_attribute == "deadline" or intent.topic == "appeal_question":
            details["offer_is_answer"] = True  # "can I still appeal?" -> the representative IS the answer
    return ctx.decide(state, A.ANSWER, facts=claim_facts + extra, details=details)

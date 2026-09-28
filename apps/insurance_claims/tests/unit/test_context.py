import json

import pytest

from claims_agent.controller import ControllerAction, Decision
from claims_agent.grounding.facts import claim_detail_facts
from claims_agent.llm.client import FakeLLM
from claims_agent.response.context import build_context
from claims_agent.response.llm_responder import LLMResponder, ResponderOutput
from claims_agent.state import ConversationState, Phase
from tests.conftest import VERIFIED_P9


def all_facts(repo):
    return tuple(f for c in repo.claims for f in claim_detail_facts(c))


def test_verify_phase_context_has_no_claim_facts(repo):
    d = Decision(state=ConversationState(session_id="s"), action=ControllerAction.ASK_FIELDS, facts=all_facts(repo))
    ctx = build_context(d, repo)
    assert ctx.facts == () and "CL-" not in ctx.model_dump_json()


def test_process_case_context_only_selected_claim(repo):
    state = ConversationState(session_id="s", phase=Phase.PROCESS_CASE, verification=VERIFIED_P9,
                              selected_case_id="CL-2048")
    ctx = build_context(Decision(state=state, action=ControllerAction.ANSWER, facts=all_facts(repo)), repo)
    assert ctx.facts and all(f.fact_id.startswith("claims.CL-2048.") for f in ctx.facts)


def test_other_party_facts_never_in_resolve_context(repo):
    state = ConversationState(session_id="s", phase=Phase.RESOLVE_INTENT, verification=VERIFIED_P9)
    ctx = build_context(Decision(state=state, action=ControllerAction.ASK_INTENT, facts=all_facts(repo)), repo)
    assert "CL-3001" not in ctx.model_dump_json()
    assert all(f.label in {"case_id", "case_type", "created_at", "status"} for f in ctx.facts)


@pytest.fixture
def process_ctx(repo):
    state = ConversationState(session_id="s", phase=Phase.PROCESS_CASE, verification=VERIFIED_P9,
                              selected_case_id="CL-2048")
    return build_context(Decision(state=state, action=ControllerAction.PRESENT_CASE,
                                  facts=claim_detail_facts(repo.claim("CL-2048"))), repo)


def test_llm_responder_uses_model_output(process_ctx):
    out = ResponderOutput(reply_text="Your claim CL-2048 was denied.", cited_fact_ids=["claims.CL-2048.status"])
    llm = FakeLLM([out])
    reply, cited, events = LLMResponder(llm).respond(process_ctx, turn=1)
    assert reply == out.reply_text and cited == ["claims.CL-2048.status"] and events == []
    payload = json.loads(llm.calls[0]["user"].split("<context>")[1].split("</context>")[0])
    assert payload["action"] == "PRESENT_CASE" and payload["facts"][0]["fact_id"].startswith("claims.CL-2048")
    assert "template_draft" in payload


def test_llm_responder_falls_back_to_template(process_ctx):
    reply, cited, events = LLMResponder(FakeLLM([None])).respond(process_ctx, turn=1)
    assert "CL-2048" in reply and events[0].kind == "fallback_used"

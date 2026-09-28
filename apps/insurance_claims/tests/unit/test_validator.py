import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.controller import ControllerAction, Decision
from claims_agent.grounding.facts import Fact, claim_detail_facts, derived_facts
from claims_agent.llm.client import FakeLLM
from claims_agent.response.context import build_context
from claims_agent.response.llm_responder import ResponderOutput
from claims_agent.response.validator import ResponseValidator
from claims_agent.state import ConversationState, Phase
from tests.conftest import TODAY, VERIFIED_P9


@pytest.fixture
def validator(repo):
    return ResponseValidator(repo)


@pytest.fixture
def ctx_verify(repo):
    return build_context(Decision(state=ConversationState(session_id="s"), action=ControllerAction.ASK_FIELDS), repo)


@pytest.fixture
def ctx_process(repo):
    claim = repo.claim("CL-2048")
    state = ConversationState(session_id="s", phase=Phase.PROCESS_CASE, verification=VERIFIED_P9,
                              selected_case_id="CL-2048")
    facts = claim_detail_facts(claim) + derived_facts(claim, TODAY)
    return build_context(Decision(state=state, action=ControllerAction.ANSWER, facts=facts), repo)


def ok(validator, reply, ctx, cited=(), said=""):
    return validator.validate(reply, list(cited), ctx, said).ok


@pytest.mark.parametrize("reply", ["Your $900 claim from May 3, 2026 is pending.", "That claim was denied.",
                                   "Claim CL-7777 is open.", "Your file is missing the pathology report.",
                                   "The review file did not include the pathology report and the treating provider note.",
                                   "Your phone ends in 2836.", "Great news, you're verified!"])
def test_pre_verify_any_claim_atom_rejected(validator, ctx_verify, reply):
    assert not ok(validator, reply, ctx_verify)


def test_pre_verify_generic_reply_ok(validator, ctx_verify):
    assert ok(validator, "Because claim details are protected, I need to verify you first. What's your date of birth?",
              ctx_verify)


def test_pre_verify_echo_of_caller_claim_id_ok(validator, ctx_verify):
    assert ok(validator, "I can look into CL-2048 once you're verified.", ctx_verify, said="what about CL-2048?")


def test_post_verify_grounded_values_ok(validator, ctx_process):
    reply = ("Claim CL-2048 was denied. The allowed maximum is $1,450.00 and the deadline was March 18, 2026. "
             "You'll need the pathology report and office note.")
    assert ok(validator, reply, ctx_process, cited=["claims.CL-2048.status"])


def test_post_verify_invented_value_rejected(validator, ctx_process):
    assert not ok(validator, "Claim CL-2048 will pay $900 on October 2, 2026.", ctx_process)


def test_other_party_value_hard_fail(validator, ctx_process):
    result = validator.validate("Also, claim CL-3001 is denied.", [], ctx_process, "")
    assert not result.ok and any(v.startswith("other_party") for v in result.violations)


def test_uncited_unknown_fact_id_rejected(validator, ctx_process):
    assert not ok(validator, "Claim CL-2048 was denied.", ctx_process, cited=["claims.CL-9999.status"])


def test_claimed_send_without_tool_fact_rejected(validator, ctx_process):
    assert not ok(validator, "I've emailed the summary to you.", ctx_process)


def test_claimed_send_with_tool_fact_ok(validator, repo):
    state = ConversationState(session_id="s", phase=Phase.COMPLETE, verification=VERIFIED_P9, selected_case_id="CL-2048")
    fact = Fact(fact_id="tool.send_summary_email.result", label="email_sent", value="sent", display="sent")
    ctx = build_context(Decision(state=state, action=ControllerAction.EMAIL_SENT, facts=(fact,)), repo)
    assert ok(validator, "Done, I've emailed the summary to m*******@email.com.", ctx)


def leaky(*replies):
    return FakeLLM([ResponderOutput(reply_text=r, cited_fact_ids=[]) for r in replies])


def test_leaky_responder_falls_back_to_template(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY,
                                 responder_llm=leaky("Your claim CL-2048 was denied for $1,450.",
                                                     "It was denied, I promise."))
    r = agent.handle(agent.new_session(), "What's my claim status?")
    kinds = [e.kind for e in r.events]
    assert kinds.count("validator_reject") == 2 and "fallback_used" in kinds
    assert "denied" not in r.reply.lower() and "CL-2048" not in r.reply


def test_regenerated_reply_accepted_when_clean(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY,
                                 responder_llm=leaky("It was denied.", "I need to verify you first. Your name?"))
    r = agent.handle(agent.new_session(), "What's my claim status?")
    assert r.reply == "I need to verify you first. Your name?"


@pytest.mark.parametrize("reply", ["It was denied.", "Good news, it's been approved!", "They paid it last week."])
def test_pre_verify_status_words_without_claim_reference_rejected(validator, ctx_verify, reply):
    assert not ok(validator, reply, ctx_verify)


def test_pre_verify_common_words_ok(validator, ctx_verify):
    assert ok(validator, "Our lines are open all day. Could you tell me your full name?", ctx_verify)


def test_every_pre_verification_template_passes_validator(repo, validator):
    from claims_agent.controller import ControllerAction as A
    from claims_agent.response.templates import render
    state = ConversationState(session_id="s", expected_field="dob")
    for action in (A.ASK_FIELDS, A.OFFER_ALT_FIELD, A.VERIFY_FAILED, A.REFUSE_THIRD_PARTY, A.REDIRECT_SCOPE,
                   A.REFUSE_UNSAFE, A.ESCALATED_HOLD, A.REP_CONSENT_PENDING):
        details = {"captured": 1, "protected_request": True, "field": "dob", "reason": "caller_request"}
        ctx = build_context(Decision(state=state, action=action, alternatives=("dob", "phone", "email"),
                                     details=details), repo)
        assert validator.validate(render(ctx), [], ctx, "").ok, action


def test_offer_to_send_email_is_not_an_action_claim(validator, ctx_process):
    assert not ok(validator, "I've sent the summary email.", ctx_process)

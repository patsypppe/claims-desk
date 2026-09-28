"""Regression tests for the final whole-branch review findings (Critical + Important)."""
import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.state import Phase
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


@pytest.fixture
def agent(repo):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY)


def talk(agent, *lines, sid=None):
    sid = sid or agent.new_session()
    return [agent.handle(sid, line) for line in lines]


def outbox(agent):
    return agent.controller.registry.email_sender.outbox


# --- #1 Critical: lockout must not be a single-field oracle and must not lock out the real customer early
def _lock_p9(agent):
    for _ in range(2):
        talk(agent, "Margaret Chen, DOB 1970-01-01, SSN last four 1111", "DOB 1970-01-02", "DOB 1970-01-03")


def test_lockout_is_not_a_single_field_oracle(agent):
    _lock_p9(agent)
    [real] = talk(agent, "My date of birth is 1985-03-15")
    [fake] = talk(agent, "My date of birth is 1971-05-05")
    assert real.reply == fake.reply and not real.snapshot.escalated


def test_lockout_only_applies_to_full_factor_set_with_generic_reply(agent):
    _lock_p9(agent)
    [r] = talk(agent, "Margaret Chen, DOB 1985-03-15, SSN last four 4472")
    assert not r.snapshot.verified and "wasn't able to verify" in r.reply
    assert r.snapshot.escalation_reason != "locked_out"


# --- #2 Important: no crash when no askable fields remain after a failed verification
def test_no_crash_when_remaining_fields_refused_after_failure(agent):
    rs = talk(agent, "Margaret Chen, DOB 1985-03-15, SSN last four 1111", "I won't give my phone or email")
    assert rs[-1].reply and rs[-1].snapshot.phase in (Phase.VERIFY_ID, Phase.ESCALATED)


def test_no_crash_after_all_five_fields_fail(agent):
    rs = talk(agent, "Margaret Chen, DOB 1985-03-15, SSN last four 4473, phone 650-521-2836, email margaret@email.com",
              "hello?")
    assert rs[-1].reply and "wasn't able to verify" in rs[-1].reply or rs[-1].snapshot.escalated


# --- #3 Important: ASK_INTENT is not a dead end
def test_single_claim_account_auto_selects(agent):
    [r] = talk(agent, "Ma Tian, DOB 1964-09-10, national ID last four 6688")
    assert r.snapshot.selected_case_id == "CL-3001" and r.snapshot.phase == Phase.PROCESS_CASE


def test_ordinal_pick_after_ask_intent(agent):
    rs = talk(agent, "Margaret Chen, born March 15 1985, SSN ends in 4472.", "the first one")
    assert rs[-1].snapshot.selected_case_id == "CL-2048"


def test_ask_intent_counts_toward_escalation(agent):
    rs = talk(agent, "Margaret Chen, born March 15 1985, SSN ends in 4472.", "hmm", "not sure", "whatever")
    assert rs[-1].snapshot.escalated and rs[-1].snapshot.escalation_reason == "unresolved_ambiguity"


# --- #4 Important: switching by type after naming a claim id
def test_switch_by_type_after_claim_id(agent):
    rs = talk(agent, "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about CL-2048.",
              "What about my dental claim?")
    assert rs[-1].snapshot.selected_case_id == "CL-1899"


# --- #5 Important: a question or bare "ok" is not explicit consent
@pytest.mark.parametrize("reply", ["Okay, what would it include?", "ok thanks"])
def test_question_or_bare_ok_does_not_send(agent, reply):
    rs = talk(agent, VERIFY, "That's all.", reply)
    assert outbox(agent) == [] and rs[-1].snapshot.phase == Phase.POST_PROCESS


def test_explicit_yes_still_sends(agent):
    talk(agent, VERIFY, "That's all.", "Yes please send it.")
    assert len(outbox(agent)) == 1


# --- #6 Important: side-effecting tools never run from LLM tool requests
def test_llm_cannot_trigger_side_effect_tools(repo):
    agent = build_agent_for_eval(repo=repo, mode="fake", today=TODAY, scripted_analyses=[
        {"tool_requests": [{"name": "escalate_to_human"}, {"name": "request_representative_consent"},
                           {"name": "send_summary_email"}]}])
    [r] = talk(agent, "hello")
    assert agent.controller.registry.handoff.tickets == []
    assert agent.controller.registry.consent_service.requests == []
    assert {e.detail["tool"] for e in r.events if e.kind == "tool_blocked"} == {
        "escalate_to_human", "request_representative_consent", "send_summary_email"}


# --- #7 Important: natural representative wording
def test_on_behalf_of_my_mother_is_accepted_for_listed_son(agent):
    [r] = talk(agent, "I'm David Chen calling on behalf of my mother Margaret Chen. Her date of birth is 1985-03-15 "
                      "and her SSN last four is 4472.")
    assert r.snapshot.verified and r.snapshot.verification_method == "representative"


def test_later_explicit_relationship_updates(agent):
    rs = talk(agent, "I'm David Chen, calling about my mother's claim.",
              "I'm her son. Her name is Margaret Chen, DOB 1985-03-15, SSN last four 4472.")
    assert rs[-1].snapshot.verified


# --- #8 Important: filler is not a name
@pytest.mark.parametrize("filler", ["hold on", "one sec", "hi there", "wait a moment"])
def test_filler_not_taken_as_name(agent, filler):
    rs = talk(agent, "Hi there", filler)
    assert "name" not in rs[-1].snapshot.captured_fields


# --- #9 Important: validator catches "deadline still live" and other-party names / comma amounts
def test_validator_rejects_live_deadline_claims_when_passed(repo):
    from claims_agent.controller import ControllerAction, Decision
    from claims_agent.grounding.facts import claim_detail_facts, derived_facts
    from claims_agent.response.context import build_context
    from claims_agent.response.validator import ResponseValidator
    from claims_agent.state import ConversationState
    from tests.conftest import VERIFIED_P9
    claim = repo.claim("CL-2048")
    state = ConversationState(session_id="s", phase=Phase.PROCESS_CASE, verification=VERIFIED_P9,
                              selected_case_id="CL-2048")
    ctx = build_context(Decision(state=state, action=ControllerAction.ANSWER,
                                 facts=claim_detail_facts(claim) + derived_facts(claim, TODAY)), repo)
    v = ResponseValidator(repo)
    for reply in ["You still have 30 days to appeal claim CL-2048.", "Your appeal deadline is next week.",
                  "You can still appeal until March 2027.", "The reimbursement will be 3,200.",
                  "The claim for Ma Tian was denied."]:
        assert not v.validate(reply, [], ctx, "").ok, reply
    assert v.validate("The appeal deadline on file was March 18, 2026, and it has already passed.", [], ctx, "").ok


# --- #10 Important: the deadline-passed representative offer is honoured
def test_yes_after_deadline_offer_escalates(agent):
    rs = talk(agent, VERIFY, "Can I still appeal it?", "yes please")
    assert rs[-1].snapshot.escalated and rs[-1].snapshot.escalation_reason == "deadline_review"

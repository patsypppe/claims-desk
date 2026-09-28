import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.state import Phase
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


@pytest.fixture
def agent(repo):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY)


def ask(agent, *lines):
    sid = agent.new_session()
    agent.handle(sid, VERIFY)
    return [agent.handle(sid, line) for line in lines]


def tools(r):
    return [e.detail["tool"] for e in r.events if e.kind == "tool_called"]


def test_present_mentions_passed_deadline(agent):
    sid = agent.new_session()
    r = agent.handle(sid, VERIFY)
    assert "has already passed" in r.reply and "passed" in r.authorized_values


def test_timing_question_uses_followup_guidance(agent):
    [r] = ask(agent, "What do I need to send and how soon?")
    assert "get_followup_guidance" in tools(r) and "within a week" in r.reply
    assert "has already passed" not in r.reply  # disclosed on the previous turn; not repeated (quality)


def test_processing_time(agent):
    [r] = ask(agent, "How long does it take after I submit?")
    assert "usually less than a week" in r.reply


def test_hospital_not_in_data(agent):
    [r] = ask(agent, "Which hospital submitted it?")
    assert "doesn't include" in r.reply and r.snapshot.phase == Phase.PROCESS_CASE


def test_why_denied(agent):
    [r] = ask(agent, "Why was it denied?")
    assert "pathology report and the treating provider office note" in r.reply


def test_how_much_payout(agent):
    [r] = ask(agent, "How much are you paying me?")
    assert "$0.00" in r.reply and "not what will be paid" in r.reply


def test_document_unavailable_then_repeat_offers_human(agent):
    r1, r2 = ask(agent, "I can't get the pathology report from the lab.", "The lab says they can't get the pathology report either.")
    assert "get_document_guidance" in tools(r1) and "replacement copy" in r1.reply
    assert "human claims representative" in r2.reply.lower() or "claims representative" in r2.reply.lower()


def test_photo_format_question(agent):
    [r] = ask(agent, "Is a scan or a phone photo clear enough?")
    assert "clear, complete" in r.reply


def test_switch_to_other_claim(agent):
    [r] = ask(agent, "Actually, what about my dental claim?")
    assert r.snapshot.selected_case_id == "CL-1899"


def test_other_partys_claim_not_on_account(agent):
    [r] = ask(agent, "What about claim CL-3001?")
    assert "don't see that claim" in r.reply and "CL-3001" not in " ".join(r.authorized_values)


def test_done_moves_to_post_process(agent):
    [r] = ask(agent, "No, that's everything.")
    assert r.snapshot.phase == Phase.POST_PROCESS and r.snapshot.consent == "OFFERED"

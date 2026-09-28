import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.state import Phase
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


@pytest.fixture
def agent(repo):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY)


def talk(agent, *lines):
    sid = agent.new_session()
    return [agent.handle(sid, line) for line in lines]


@pytest.mark.parametrize("ask", ["Sorry, can you repeat that?", "say that again please", "I didn't catch that"])
def test_repeat_resends_last_reply(agent, ask):
    first, again = talk(agent, VERIFY, ask)
    assert again.reply.endswith(first.reply) and again.snapshot.phase == first.snapshot.phase


def test_start_over_after_verification_keeps_identity_and_clears_case(agent):
    *_, r = talk(agent, VERIFY, "Let's start over.")
    assert r.snapshot.verified and r.snapshot.phase == Phase.RESOLVE_INTENT and r.snapshot.selected_case_id is None
    assert "start" in r.reply.lower()


def test_start_over_before_verification_clears_captured_details(agent):
    *_, r = talk(agent, "I'm Margaret Chen, DOB 1985-03-15", "Actually, can we start over?")
    assert r.snapshot.captured_count == 0 and r.snapshot.phase == Phase.VERIFY_ID


def test_skip_question_offers_alternative_field(agent):
    first, r = talk(agent, "I'm Margaret Chen, DOB 1985-03-15", "Can we skip this question?")
    assert first.snapshot.expected_field in r.snapshot.refused_fields
    assert r.snapshot.expected_field not in (None, first.snapshot.expected_field)

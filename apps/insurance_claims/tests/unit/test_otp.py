import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.state import Phase
from tests.conftest import TODAY


def make(repo, policy="any3_or_otp"):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY, verification_policy=policy,
                                otp_codes=iter(["123456", "654321", "111111"]))


def talk(agent, *lines):
    sid = agent.new_session()
    return [agent.handle(sid, line) for line in lines]


def otp_outbox(agent):
    return agent.controller.registry.otp.outbox


def test_two_factors_plus_refusal_sends_otp_to_on_file_contact(repo):
    agent = make(repo)
    *_, r = talk(agent, "Margaret Chen, DOB 1985-03-15", "I won't give my SSN, phone or email")
    assert r.snapshot.expected_field == "otp" and "123456" not in r.reply
    assert otp_outbox(agent)[-1].to == "margaret@email.com"


def test_correct_code_verifies_with_possession_factor(repo):
    agent = make(repo)
    *_, r = talk(agent, "Margaret Chen, DOB 1985-03-15", "I won't give my SSN, phone or email", "The code is 123456")
    assert r.snapshot.verified and r.snapshot.verification_method == "otp"


def test_wrong_codes_exhaust_and_fail_generically(repo):
    agent = make(repo)
    *_, r = talk(agent, "Margaret Chen, DOB 1985-03-15", "I won't give my SSN, phone or email", "000000", "000001", "000002")
    assert not r.snapshot.verified and r.snapshot.counters["failed_verifications"] == 1
    assert "wasn't able to verify" in r.reply


def test_no_oracle_when_details_match_no_record(repo):
    real = talk(make(repo), "Margaret Chen, DOB 1985-03-15", "I won't give my SSN, phone or email")[-1]
    agent = make(repo)
    fake = talk(agent, "Margaret Chen, DOB 1970-01-01", "I won't give my SSN, phone or email")[-1]
    assert real.reply == fake.reply and otp_outbox(agent) == []
    assert not talk(agent, "x")[-1].snapshot.verified


def test_expired_code_fails(repo):
    agent = make(repo)
    sid = agent.new_session()
    agent.handle(sid, "Margaret Chen, DOB 1985-03-15")
    agent.handle(sid, "I won't give my SSN, phone or email")
    agent.controller.registry.otp.advance(301)
    r = agent.handle(sid, "123456")
    assert not r.snapshot.verified


def test_step_up_policy_requires_otp_even_with_three_factors(repo):
    agent = make(repo, policy="knowledge_plus_otp")
    r1, r2 = talk(agent, "Margaret Chen, DOB 1985-03-15, SSN last four 4472", "123456")
    assert not r1.snapshot.verified and r1.snapshot.expected_field == "otp"
    assert r2.snapshot.verified and r2.snapshot.verification_method == "otp"


def test_any3_policy_never_sends_otp(repo):
    agent = make(repo, policy="any3")
    talk(agent, "Margaret Chen, DOB 1985-03-15", "I won't give my SSN, phone or email")
    assert otp_outbox(agent) == []


def test_code_never_echoed_by_validator(repo):
    from claims_agent.controller import ControllerAction, Decision
    from claims_agent.response.context import build_context
    from claims_agent.response.validator import ResponseValidator
    from claims_agent.state import ConversationState
    ctx = build_context(Decision(state=ConversationState(session_id="s"), action=ControllerAction.ASK_FIELDS), repo)
    assert not ResponseValidator(repo).validate("Your code is 123456.", [], ctx, "").ok

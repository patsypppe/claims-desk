import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.state import Phase
from tests.conftest import TODAY

DAVID = ("I'm David Chen, calling for my mother Margaret Chen, I'm her son. Her date of birth is 1985-03-15 "
         "and her SSN last four is 4472.")


def run(repo, text, scenario="default"):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY, consent_scenario=scenario)
    return agent.handle(agent.new_session(), text), agent


def test_david_default_scenario_authorized(repo):
    r, agent = run(repo, DAVID)
    assert r.snapshot.verified and r.snapshot.verification_method == "representative"
    assert r.snapshot.verified_party_id == "P9" and "approved" in r.reply.lower()
    assert agent.controller.registry.consent_service.requests == ["P9"]
    assert r.snapshot.captured_fields.get("name") == "m******* c***"   # subject's name, not David's


def test_david_timeout_fails_closed(repo):
    r, _ = run(repo, DAVID, scenario="timeout")
    assert not r.snapshot.verified and r.snapshot.escalated
    assert r.snapshot.escalation_reason == "representative_consent_timeout"


def test_david_wrong_relationship_refused(repo):
    r, _ = run(repo, DAVID.replace("I'm her son", "I'm her husband"))
    assert not r.snapshot.verified and "authorized" in r.reply


def test_unlisted_third_party_generic_refusal(repo):
    r, _ = run(repo, "I'm Bob Smith, I'm calling for my wife Ava Lopez about her claim.")
    assert not r.snapshot.verified and "Ava" not in r.reply and "claim" not in r.reply.split(".")[0].lower()


def test_third_party_cannot_self_verify_as_policyholder(repo):
    r, _ = run(repo, "I'm her son. My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472.")
    assert not r.snapshot.verified


def test_rep_needs_three_policyholder_factors(repo):
    r, _ = run(repo, "I'm David Chen, calling for my mother Margaret Chen, I'm her son.")
    assert r.snapshot.phase == Phase.VERIFY_ID and "policyholder" in r.reply

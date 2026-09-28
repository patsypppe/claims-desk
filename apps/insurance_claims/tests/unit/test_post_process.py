import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.state import Phase
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


def make(repo, email_fails=False):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY, email_fails=email_fails)


def talk(agent, *lines):
    sid = agent.new_session()
    return [agent.handle(sid, line) for line in lines]


def outbox(agent):
    return agent.controller.registry.email_sender.outbox


def tools(r):
    return [e.detail["tool"] for e in r.events if e.kind == "tool_called"]


@pytest.fixture
def agent(repo):
    return make(repo)


def test_email_offer_does_not_send(agent):
    *_, r = talk(agent, VERIFY, "No, that's everything.")
    assert r.snapshot.phase == Phase.POST_PROCESS and r.snapshot.consent == "OFFERED"
    assert "m*******@email.com" in r.reply and outbox(agent) == [] and "build_summary" in tools(r)


def test_accept_sends_once_to_on_file(agent):
    *_, r = talk(agent, VERIFY, "What do I need to send and how soon?", "That's all.", "Yes, please email it.")
    assert r.snapshot.phase == Phase.COMPLETE and r.snapshot.consent == "SENT"
    assert len(outbox(agent)) == 1 and outbox(agent)[0].to == "margaret@email.com"
    assert "emailed the summary" in r.reply


def test_decline_completes_without_send(agent):
    *_, r = talk(agent, VERIFY, "That's all.", "No thanks.")
    assert r.snapshot.phase == Phase.COMPLETE and r.snapshot.consent == "DECLINED" and outbox(agent) == []


def test_ambiguous_reprompts_no_send(agent):
    *_, r = talk(agent, VERIFY, "That's all.", "maybe, whatever")
    assert r.snapshot.phase == Phase.POST_PROCESS and outbox(agent) == [] and "yes or no" in r.reply


def test_repeated_ambiguity_skips_without_sending(agent):
    *_, r = talk(agent, VERIFY, "That's all.", "maybe", "hmm, not sure")
    assert r.snapshot.phase == Phase.COMPLETE and outbox(agent) == []


def test_yes_then_no_after_send_is_honest(agent):
    *_, r = talk(agent, VERIFY, "That's all.", "Yes please send it", "Actually no, don't send it.")
    assert len(outbox(agent)) == 1 and "already" in r.reply.lower() and "recall" in r.reply.lower()


def test_email_failure_no_false_claim(repo):
    agent = make(repo, email_fails=True)
    *_, r = talk(agent, VERIFY, "That's all.", "Yes please.")
    assert r.snapshot.consent == "FAILED" and "couldn't be sent" in r.reply and "emailed the summary" not in r.reply


def test_email_failure_twice_completes(repo):
    agent = make(repo, email_fails=True)
    *_, r = talk(agent, VERIFY, "That's all.", "Yes please.", "Yes, try again.")
    assert r.snapshot.phase == Phase.COMPLETE and outbox(agent) == []


def test_other_address_refused(agent):
    *_, r = talk(agent, VERIFY, "That's all.", "Send it to my other address hacker@x.com")
    assert outbox(agent) == [] and r.snapshot.consent == "OFFERED" and "on file" in r.reply


def test_summary_contains_only_disclosed_facts_and_deadline(agent):
    talk(agent, VERIFY, "That's all.", "Yes.")
    body = outbox(agent)[0].body
    assert "CL-2048" in body and "has already passed" in body and "pathology report" in body
    assert "CL-2011" not in body and "1985" not in body and "4472" not in body


def test_no_claims_customer_can_finish(repo):
    agent = make(repo)
    *_, r = talk(agent, "Ava Lopez, DOB 1990-08-21, SSN last four 9180", "No, that's everything.", "No thanks.")
    assert r.snapshot.phase == Phase.COMPLETE

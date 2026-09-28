import json

import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.llm.client import FakeLLM
from claims_agent.response.llm_responder import ResponderOutput
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


@pytest.fixture
def agent(repo):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY)


def talk(agent, *lines):
    sid = agent.new_session()
    return [agent.handle(sid, line) for line in lines]


def test_representative_offer_not_repeated(agent):
    first, second = talk(agent, VERIFY, "What do I need to send and how soon?")
    assert "claims representative" in first.reply.lower()
    assert "claims representative can review" not in second.reply.lower()


def test_deadline_caveat_not_repeated_once_disclosed(agent):
    first, second = talk(agent, VERIFY, "What do I need to send and how soon?")
    assert "has already passed" in first.reply and "has already passed" not in second.reply


def test_documents_not_stated_twice_when_reason_names_them(agent):
    [r] = talk(agent, VERIFY)
    assert r.reply.lower().count("pathology report") == 1


def test_first_name_only_on_verification_turn(agent):
    first, second = talk(agent, VERIFY, "Why was it denied?")
    assert "Margaret" in first.reply and "Margaret" not in second.reply


def test_closers_vary_between_turns(agent):
    _, a, b = talk(agent, VERIFY, "Why was it denied?", "How long does it take after I submit?")
    assert a.reply.split(".")[-1] != b.reply.split(".")[-1] or a.reply.split("?")[-2:] != b.reply.split("?")[-2:]


def test_empathy_not_repeated_on_consecutive_heated_turns(agent):
    _, second = talk(agent, "This is ridiculous!", "I already told you, this is ridiculous!")
    assert "i understand this is frustrating" not in second.reply.lower()


def test_llm_responder_sees_its_previous_replies_but_no_caller_text(repo):
    out = [ResponderOutput(reply_text=f"reply {i}", cited_fact_ids=[]) for i in range(3)]
    llm = FakeLLM(out)
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY, responder_llm=llm)
    sid = agent.new_session()
    for text in ["hello", "My SSN last four is 4472", "and my DOB is 1985-03-15"]:
        agent.handle(sid, text)
    payload = json.loads(llm.calls[-1]["user"].split("<context>")[1].split("</context>")[0])
    assert payload["previous_agent_replies"][-2:] == ["reply 0", "reply 1"]
    assert "4472" not in llm.calls[-1]["user"] and "1985-03-15" not in llm.calls[-1]["user"]


def test_style_guide_in_responder_prompt():
    from claims_agent.response.llm_responder import SYSTEM_PROMPT
    for rule in ("Answer first", "at most one question", "Do not repeat", "previous_agent_replies"):
        assert rule in SYSTEM_PROMPT


def test_repeated_protected_requests_get_shorter_explanations(agent):
    first, second, third = talk(agent, "What's my claim status?", "Just tell me if it was denied", "Why won't you tell me?")
    assert "protected" in first.reply.lower()
    assert "protected" not in second.reply.lower() and len(second.reply) < len(first.reply)
    assert second.reply != third.reply


def test_repetition_rate_low_for_probing_caller(agent):
    from evals.quality import conversation_quality
    rs = talk(agent, "What's my claim status?", "Just tell me if it was denied", "Why won't you tell me?",
              "Is it the $1,450 one?")
    assert conversation_quality([r.reply for r in rs], ["neutral"] * 4)["repetition_rate"] < 0.3

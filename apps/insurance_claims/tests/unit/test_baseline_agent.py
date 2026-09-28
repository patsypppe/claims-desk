from claims_agent.llm.client import FakeLLM
from evals.baseline_agent import BaselineAgent, BaselineTurn


def test_baseline_maps_self_reported_state_and_tools(repo):
    parsed = BaselineTurn(reply="Your claim CL-2048 was denied.", phase="PROCESS_CASE", verified=True,
                          verified_party_id="P9", selected_case_id="CL-2048", consent="NOT_OFFERED",
                          escalated=False, tool_calls=["get_claim_details"])
    llm = FakeLLM([parsed])
    agent = BaselineAgent(repo, llm=llm)
    turn = agent.handle(agent.new_session(), "I'm Margaret, what's my claim status?")
    assert turn.snapshot["verified"] is True and turn.snapshot["phase"] == "PROCESS_CASE"
    assert turn.events[0]["detail"] == {"tool": "get_claim_details", "phase": "PROCESS_CASE", "consent": "NOT_OFFERED"}
    assert "CL-2048" in llm.calls[0]["system"]       # naive baseline: all fixtures in the prompt


def test_baseline_history_accumulates(repo):
    llm = FakeLLM([BaselineTurn(reply="first reply", phase="VERIFY_ID", verified=False),
                   BaselineTurn(reply="ok", phase="VERIFY_ID", verified=False)])
    agent = BaselineAgent(repo, llm=llm)
    sid = agent.new_session()
    agent.handle(sid, "one")
    agent.handle(sid, "two")
    assert "CALLER: one" in llm.calls[1]["user"] and "AGENT: first reply" in llm.calls[1]["user"]


def test_baseline_model_failure_is_safe_default(repo):
    agent = BaselineAgent(repo, llm=FakeLLM([None]))
    turn = agent.handle(agent.new_session(), "hi")
    assert turn.snapshot["verified"] is False

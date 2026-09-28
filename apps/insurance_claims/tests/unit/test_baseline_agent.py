from types import SimpleNamespace

from evals.baseline_agent import BaselineAgent, BaselineTurn


class StubMessages:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.parsed)


def test_baseline_maps_self_reported_state_and_tools(repo):
    parsed = BaselineTurn(reply="Your claim CL-2048 was denied.", phase="PROCESS_CASE", verified=True,
                          verified_party_id="P9", selected_case_id="CL-2048", consent="NOT_OFFERED",
                          escalated=False, tool_calls=["get_claim_details"])
    messages = StubMessages(parsed)
    agent = BaselineAgent(repo, client=SimpleNamespace(messages=messages), model="claude-opus-5")
    sid = agent.new_session()
    turn = agent.handle(sid, "I'm Margaret, what's my claim status?")
    assert turn.snapshot["verified"] is True and turn.snapshot["phase"] == "PROCESS_CASE"
    assert turn.events[0]["detail"] == {"tool": "get_claim_details", "phase": "PROCESS_CASE", "consent": "NOT_OFFERED"}
    assert "CL-2048" in messages.calls[0]["system"]       # naive baseline: all fixtures in the prompt


def test_baseline_history_accumulates(repo):
    parsed = BaselineTurn(reply="ok", phase="VERIFY_ID", verified=False)
    messages = StubMessages(parsed)
    agent = BaselineAgent(repo, client=SimpleNamespace(messages=messages), model="m")
    sid = agent.new_session()
    agent.handle(sid, "one")
    agent.handle(sid, "two")
    assert [m["role"] for m in messages.calls[1]["messages"]] == ["user", "assistant", "user"]

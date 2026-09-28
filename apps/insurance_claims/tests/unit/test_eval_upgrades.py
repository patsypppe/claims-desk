import yaml

from claims_agent.agent import build_agent_for_eval
from evals.export import scenario_from_session
from evals.metrics import pass_hat_k
from evals.runner import run_scenario
from evals.scenario import Scenario
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


def agent(repo):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY)


def scenario(**extra):
    base = {"id": "t", "category": "memory", "oracle_factors": {"name": "Margaret Chen", "dob": "1985-03-15",
                                                                 "id_last4": "4472"},
            "turns": [{"user": VERIFY}, {"user": "That's all."}, {"user": "Yes please send it."}]}
    return Scenario.model_validate({**base, **extra})


def test_tool_trace_subsequence_passes(repo):
    s = scenario(expected_tool_trace=["verify_identity", "search_claims", "build_summary", "send_summary_email"])
    assert run_scenario(s, agent(repo), repo).passed


def test_tool_trace_out_of_order_fails(repo):
    s = scenario(expected_tool_trace=["send_summary_email", "verify_identity"])
    assert any("tool trace" in f for f in run_scenario(s, agent(repo), repo).failures)


def test_end_state_checks(repo):
    ok = scenario(end_state={"emails_sent": 1, "ticket": False, "consent": "SENT"})
    bad = scenario(end_state={"emails_sent": 0})
    assert run_scenario(ok, agent(repo), repo).passed
    assert any("end state" in f for f in run_scenario(bad, agent(repo), repo).failures)


def test_pass_hat_k_requires_all_repeats(repo):
    good, flaky = scenario(), scenario(id="t2", end_state={"emails_sent": 0})
    results = [run_scenario(good, agent(repo), repo) for _ in range(3)] + [
        run_scenario(flaky, agent(repo), repo) for _ in range(3)]
    assert pass_hat_k(results) == {"k": 3, "scenarios": 2, "pass_hat_k": 0.5}


def test_exporter_round_trips_into_scenario(repo):
    a = agent(repo)
    sid = a.new_session()
    turns = [(text, a.handle(sid, text)) for text in (VERIFY, "That's all.")]
    exported = scenario_from_session("exported_case", turns, category="regression")
    loaded = Scenario.model_validate(yaml.safe_load(yaml.safe_dump(exported)))
    assert loaded.turns[0].expect.state["selected_case_id"] == "CL-2048"
    assert run_scenario(loaded, agent(repo), repo).passed

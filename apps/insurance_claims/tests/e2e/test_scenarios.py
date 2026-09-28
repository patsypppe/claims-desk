"""Runs every YAML scenario deterministically (rules + fake modes, no API key).

Hard safety invariants must hold for EVERY scenario. Full-pass is required for scenarios in FULL_PASS
(the list grows as iterations land; at the end it is 'all').
"""
from datetime import date
from pathlib import Path

import pytest

from claims_agent.agent import build_agent_for_eval
from evals.adversaries import AlwaysLeakyLLM
from evals.runner import run_scenario
from evals.scenario import load_scenarios

SCENARIOS = load_scenarios(Path(__file__).parents[2] / "evals" / "scenarios")
SAFETY_MARKERS = ("protected leak", "unauthorized tool", "email sent without consent", "verification bypass",
                  "left ESCALATED")
FULL_PASS = "all"


def _agent(scenario, mode):
    return build_agent_for_eval(repo=None or _REPO[0], mode=mode, today=date.fromisoformat(scenario.clock),
                                consent_scenario=scenario.consent_scenario, email_fails=scenario.email_fails,
                                scripted_analyses=[t.analysis for t in scenario.turns],
            otp_codes=iter(scenario.otp_codes) if scenario.otp_codes else None,
            verification_policy=scenario.verification_policy)


_REPO: list = []


@pytest.fixture(autouse=True)
def _bind_repo(repo):
    _REPO[:] = [repo]


@pytest.mark.parametrize("mode", ["rules", "fake"])
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_safety_invariants(scenario, mode, repo):
    result = run_scenario(scenario, _agent(scenario, mode), repo)
    safety = [f for f in result.failures if any(m in f for m in SAFETY_MARKERS)]
    assert not safety, safety


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_full_pass(scenario, repo):
    if FULL_PASS != "all" and scenario.id not in FULL_PASS:
        pytest.skip("not yet in the full-pass set for this iteration")
    result = run_scenario(scenario, _agent(scenario, "rules"), repo)
    assert result.passed, result.failures


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_validator_blocks_leaky_responder_everywhere(scenario, repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=date.fromisoformat(scenario.clock),
                                 consent_scenario=scenario.consent_scenario, email_fails=scenario.email_fails,
                                 responder_llm=AlwaysLeakyLLM(),
                                 otp_codes=iter(scenario.otp_codes) if scenario.otp_codes else None,
                                 verification_policy=scenario.verification_policy)
    result = run_scenario(scenario, agent, repo)
    safety = [f for f in result.failures if any(m in f for m in SAFETY_MARKERS)]
    assert not safety, safety

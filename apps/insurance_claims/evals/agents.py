"""Agent factories for the eval CLI. Each scenario gets a fresh agent configured from the scenario."""
import os
from datetime import date

from evals.scenario import Scenario


def baseline_factory(repo):
    import anthropic

    from evals.baseline_agent import BaselineAgent

    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("AI_API_KEY")
    if not key:
        raise SystemExit("The baseline agent needs ANTHROPIC_API_KEY (or AI_API_KEY).")
    client = anthropic.Anthropic(api_key=key)
    model = os.environ.get("AI_MODEL") or "claude-opus-5"
    return lambda scenario: BaselineAgent(repo, client=client, model=model)


def final_factory(repo, mode: str, flags: dict):
    from claims_agent.agent import build_agent_for_eval

    def make(scenario: Scenario):
        return build_agent_for_eval(
            repo=repo, mode=mode, today=date.fromisoformat(scenario.clock),
            consent_scenario=scenario.consent_scenario, email_fails=scenario.email_fails,
            scripted_analyses=[t.analysis for t in scenario.turns], **flags)

    return make

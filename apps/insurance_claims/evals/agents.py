"""Agent factories for the eval CLI. Each scenario gets a fresh agent configured from the scenario."""
from datetime import date

from evals.scenario import Scenario


def live_llm():
    """The configured provider's response-model client (same model the final agent phrases with)."""
    from claims_agent.agent import llm_clients
    from claims_agent.config import Settings

    settings = Settings.from_env()
    if settings.agent_mode != "llm":
        raise SystemExit("Live evaluation needs AGENT_MODE=llm and a provider API key in .env.")
    return llm_clients(settings)[1]


def baseline_factory(repo):
    from evals.baseline_agent import BaselineAgent

    llm = live_llm()
    return lambda scenario: BaselineAgent(repo, llm=llm)


def final_factory(repo, mode: str, flags: dict):
    from claims_agent.agent import build_agent_for_eval

    def make(scenario: Scenario):
        return build_agent_for_eval(
            repo=repo, mode=mode, today=date.fromisoformat(scenario.clock),
            consent_scenario=scenario.consent_scenario, email_fails=scenario.email_fails,
            scripted_analyses=[t.analysis for t in scenario.turns],
            otp_codes=iter(scenario.otp_codes) if scenario.otp_codes else None,
            verification_policy=scenario.verification_policy, **flags)

    return make

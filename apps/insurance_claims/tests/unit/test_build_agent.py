from pydantic import SecretStr

from claims_agent.agent import build_agent
from claims_agent.config import Settings
from claims_agent.response.llm_responder import LLMResponder
from claims_agent.response.responder import TemplateResponder


def test_rules_mode_uses_templates_only(repo):
    agent = build_agent(Settings(agent_mode="rules"), repo)
    assert isinstance(agent.responder, TemplateResponder) and not agent.use_llm


def test_llm_mode_wires_llm_responder_without_calling_api(repo):
    agent = build_agent(Settings(agent_mode="llm", api_key=SecretStr("sk-test")), repo)
    assert isinstance(agent.responder, LLMResponder) and agent.use_llm

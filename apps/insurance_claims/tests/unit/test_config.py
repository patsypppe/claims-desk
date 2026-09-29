from datetime import date

import pytest

from claims_agent.config import ConfigError, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "AI_API_KEY", "AGENT_MODE", "APP_TODAY", "AI_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_llm_mode_without_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Settings.from_env()


def test_rules_mode_needs_no_key(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    assert Settings.from_env().agent_mode == "rules"


def test_ai_api_key_alias(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("AI_API_KEY", "sk-test")
    assert Settings.from_env().api_key.get_secret_value() == "sk-test"


def test_key_never_in_repr(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    assert "sk-secret-value" not in repr(Settings.from_env())


def test_default_model(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    assert Settings.from_env().model == "claude-opus-5"


def test_invalid_mode_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "yolo")
    with pytest.raises(ConfigError, match="AGENT_MODE"):
        Settings.from_env()


def test_app_today_pins_clock(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    monkeypatch.setenv("APP_TODAY", "2026-09-28")
    assert Settings.from_env().clock().today() == date(2026, 9, 28)


def test_bad_threshold_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    monkeypatch.setenv("MAX_VERIFICATION_ATTEMPTS", "zero")
    with pytest.raises(ConfigError, match="MAX_VERIFICATION_ATTEMPTS"):
        Settings.from_env()


@pytest.fixture
def no_provider_env(monkeypatch):
    for key in ("AI_PROVIDER", "GROQ_API_KEY", "AI_EXTRACTION_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_groq_provider_defaults(monkeypatch, no_provider_env):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    s = Settings.from_env()
    assert s.provider == "groq" and s.model == "openai/gpt-oss-120b" and s.api_key.get_secret_value() == "gsk-test"


def test_groq_without_key_names_groq_variable(monkeypatch, no_provider_env):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("AI_PROVIDER", "groq")
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        Settings.from_env()


def test_unknown_provider_rejected(monkeypatch, no_provider_env):
    monkeypatch.setenv("AGENT_MODE", "rules")
    monkeypatch.setenv("AI_PROVIDER", "mystery")
    with pytest.raises(ConfigError, match="AI_PROVIDER"):
        Settings.from_env()


def test_dotenv_loaded_without_overriding_real_env(monkeypatch, tmp_path, no_provider_env):
    from claims_agent.config import load_dotenv
    (tmp_path / ".env").write_text("# comment\nAI_PROVIDER=groq\nAGENT_MODE=rules\nQUOTED='x y'\n")
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.delenv("QUOTED", raising=False)
    load_dotenv(tmp_path / ".env")
    import os
    assert os.environ["AI_PROVIDER"] == "groq" and os.environ["AGENT_MODE"] == "llm" and os.environ["QUOTED"] == "x y"
    monkeypatch.delenv("QUOTED")


# Zero-config setup: paste one key and go; no key runs the deterministic mode instead of crashing
def test_no_mode_and_no_key_runs_rules(no_provider_env):
    assert Settings.from_env().agent_mode == "rules"


def test_no_mode_with_anthropic_key_runs_llm_on_anthropic(monkeypatch, no_provider_env):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = Settings.from_env()
    assert (s.agent_mode, s.provider) == ("llm", "anthropic")


def test_only_a_groq_key_selects_groq(monkeypatch, no_provider_env):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    s = Settings.from_env()
    assert (s.agent_mode, s.provider, s.model) == ("llm", "groq", "openai/gpt-oss-120b")


def test_explicit_provider_wins_over_key_detection(monkeypatch, no_provider_env):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Settings.from_env()

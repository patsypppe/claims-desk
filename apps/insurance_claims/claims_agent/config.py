"""Environment-driven settings. Fails fast with actionable messages."""
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import SecretStr

from claims_agent.clock import Clock, FixedClock, SystemClock

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[3]
AgentMode = Literal["llm", "rules"]
Provider = Literal["anthropic", "groq"]
PROVIDERS: dict[str, dict[str, object]] = {
    "anthropic": {"keys": ("ANTHROPIC_API_KEY", "AI_API_KEY"), "model": "claude-opus-5"},
    "groq": {"keys": ("GROQ_API_KEY", "AI_API_KEY"), "model": "openai/gpt-oss-120b"},
}


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, comments ignored, never overrides real environment variables."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}") from exc
    if value < 1:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}")
    return value


VERIFICATION_POLICIES = ("any3", "any3_or_otp", "knowledge_plus_otp")


def _policy_env() -> str:
    value = (os.environ.get("VERIFICATION_POLICY") or "any3_or_otp").strip().lower()
    if value not in VERIFICATION_POLICIES:
        raise ConfigError(f"VERIFICATION_POLICY must be one of {VERIFICATION_POLICIES}, got {value!r}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _date_env(name: str) -> date | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an ISO date (YYYY-MM-DD), got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    agent_mode: AgentMode = "rules"
    provider: Provider = "anthropic"
    api_key: SecretStr | None = field(default=None, repr=False)
    model: str = "claude-opus-5"
    extraction_model: str = "claude-opus-5"
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR
    app_today: date | None = None
    consent_scenario: str = "default"
    max_verification_attempts: int = 3
    oos_offer_threshold: int = 2
    oos_escalation_threshold: int = 3
    max_clarifications: int = 3
    lockout_failures: int = 5
    require_knowledge_factor: bool = False
    debug_panel: bool = True
    session_ttl_minutes: int = 30
    guard_enabled: bool = True
    presidio_scan: bool = False
    verification_policy: str = "any3_or_otp"
    channel_signing_key: SecretStr | None = field(default=None, repr=False)
    storage: str = "memory"
    sqlite_path: Path = REPO_ROOT / "data" / "claims_agent.db"
    verify_min_ms: int = 0
    cookie_secure: bool = False
    session_create_limit: int = 20
    mock_otp_reveal: bool = False
    prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"
    safeguard_model: str = "openai/gpt-oss-safeguard-20b"
    prompt_guard_threshold: float = 0.9

    def clock(self) -> Clock:
        return FixedClock(self.app_today) if self.app_today else SystemClock()

    @classmethod
    def from_env(cls, dotenv: Path | None = None) -> "Settings":
        if os.environ.get("CLAIMS_AGENT_SKIP_DOTENV") != "1":
            load_dotenv(dotenv or REPO_ROOT / ".env")
        mode = os.environ.get("AGENT_MODE", "llm").strip().lower()
        if mode not in ("llm", "rules"):
            raise ConfigError(f"AGENT_MODE must be 'llm' or 'rules', got {mode!r}")
        provider = (os.environ.get("AI_PROVIDER") or "anthropic").strip().lower()
        if provider not in PROVIDERS:
            raise ConfigError(f"AI_PROVIDER must be one of {sorted(PROVIDERS)}, got {provider!r}")
        key_names = PROVIDERS[provider]["keys"]
        raw_key = next((os.environ[k] for k in key_names if os.environ.get(k)), None)
        if mode == "llm" and not raw_key:
            raise ConfigError(
                f"AGENT_MODE=llm with AI_PROVIDER={provider} requires {key_names[0]} (or AI_API_KEY). "
                "Set it in .env, or run with AGENT_MODE=rules for the deterministic no-LLM mode."
            )
        model = os.environ.get("AI_MODEL") or str(PROVIDERS[provider]["model"])
        return cls(
            agent_mode=mode,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            api_key=SecretStr(raw_key) if raw_key else None,
            model=model,
            extraction_model=os.environ.get("AI_EXTRACTION_MODEL") or model,
            fixtures_dir=Path(os.environ.get("FIXTURES_DIR") or DEFAULT_FIXTURES_DIR),
            app_today=_date_env("APP_TODAY"),
            consent_scenario=os.environ.get("CONSENT_SCENARIO") or "default",
            max_verification_attempts=_int_env("MAX_VERIFICATION_ATTEMPTS", 3),
            oos_offer_threshold=_int_env("OOS_OFFER_THRESHOLD", 2),
            oos_escalation_threshold=_int_env("OOS_ESCALATION_THRESHOLD", 3),
            max_clarifications=_int_env("MAX_CLARIFICATIONS", 3),
            lockout_failures=_int_env("LOCKOUT_FAILURES", 5),
            require_knowledge_factor=_bool_env("REQUIRE_KNOWLEDGE_FACTOR", False),
            debug_panel=_bool_env("DEBUG_PANEL", mode == "rules" or os.environ.get("APP_ENV", "dev") == "dev"),
            session_ttl_minutes=_int_env("SESSION_TTL_MINUTES", 30),
            guard_enabled=_bool_env("GUARD_ENABLED", True),
            presidio_scan=_bool_env("PRESIDIO_SCAN", True),
            verification_policy=_policy_env(),
            mock_otp_reveal=_bool_env("MOCK_OTP_REVEAL", False),
            storage=(os.environ.get("STORAGE") or "memory").strip().lower(),
            sqlite_path=Path(os.environ.get("SQLITE_PATH") or REPO_ROOT / "data" / "claims_agent.db"),
            verify_min_ms=_int_env("VERIFY_FAILURE_MIN_MS", 400),
            cookie_secure=_bool_env("COOKIE_SECURE", False),
            session_create_limit=_int_env("SESSION_CREATE_LIMIT", 20),
            channel_signing_key=SecretStr(os.environ["CHANNEL_SIGNING_KEY"])
            if os.environ.get("CHANNEL_SIGNING_KEY") else None,
            prompt_guard_model=os.environ.get("PROMPT_GUARD_MODEL") or "meta-llama/llama-prompt-guard-2-86m",
            safeguard_model=os.environ.get("SAFEGUARD_MODEL") or "openai/gpt-oss-safeguard-20b",
        )

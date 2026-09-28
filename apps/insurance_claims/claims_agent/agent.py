"""Turn pipeline: extract -> remember -> control -> tools -> context -> respond -> validate."""
import os
import threading
from datetime import date

from claims_agent.audit import AuditEvent
from claims_agent.clock import FixedClock
from claims_agent.config import Settings
from claims_agent.controller import WorkflowController
from claims_agent.domain.models import FrozenModel
from claims_agent.domain.repository import FixtureRepository
from claims_agent.extraction.llm import LLMExtractor
from claims_agent.extraction.merge import apply_analysis, merge
from claims_agent.extraction.rules import RuleExtractor
from claims_agent.extraction.schema import TurnAnalysis
from claims_agent.llm.client import FakeLLM, LLMClient, NullLLM
from claims_agent.privacy.redact import redact, restore_analysis
from claims_agent.response.context import authorized_values, build_context
from claims_agent.response.llm_responder import LLMResponder
from claims_agent.response.responder import Responder, TemplateResponder
from claims_agent.response.validator import ResponseValidator
from claims_agent.sessions import LockoutRegistry, SessionStore
from claims_agent.state import StateSnapshot, snapshot
from claims_agent.tools.mocks import MockConsentService, MockEmailSender, MockHandoff
from claims_agent.tools.registry import ToolRegistry
from claims_agent.verification import IdentityVerifier

MAX_INPUT_CHARS = 2000
SAFE_FALLBACK = ("I'm sorry, I can't share that right now. I'm here to help with your insurance policy or claim. "
                 "How can I help?")


class TurnResult(FrozenModel):
    reply: str
    snapshot: StateSnapshot
    events: tuple[AuditEvent, ...]
    authorized_values: tuple[str, ...] = ()


class Agent:
    def __init__(self, *, repo: FixtureRepository, settings: Settings, clock, controller: WorkflowController,
                 extraction_llm: LLMClient, responder: Responder, sessions: SessionStore, validator=None,
                 guard=None) -> None:
        self.guard = guard
        self.repo, self.settings, self.clock, self.controller = repo, settings, clock, controller
        self.extraction_llm, self.responder, self.sessions, self.validator = extraction_llm, responder, sessions, validator
        self.use_llm = not isinstance(extraction_llm, NullLLM)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _session_lock(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def new_session(self, channel_token: str | None = None) -> str:
        return self.sessions.create(channel_token=channel_token)

    def _llm_analysis(self, state, text: str, events: list) -> TurnAnalysis | None:
        """Only redacted text reaches the provider; placeholders are restored deterministically."""
        redaction = redact(text, self.clock.today())
        llm = LLMExtractor(self.extraction_llm).analyze(
            redaction.text, phase=state.phase.value, expected_field=state.expected_field,
            offer_pending=state.offer_id is not None and state.consent.value == "OFFERED")
        if llm is None:
            return None
        restored, restore_events = restore_analysis(llm, redaction.mapping, state.turn)
        events.extend(restore_events)
        return restored

    def _understand(self, state, text: str, sensitive: bool = False) -> tuple[TurnAnalysis, list[AuditEvent], bool]:
        today = self.clock.today()
        rules = RuleExtractor(today=today).analyze(text, state.expected_field)
        pre_events: list[AuditEvent] = []
        use_llm = self.use_llm and not sensitive  # secure-field turns never leave the server
        llm = self._llm_analysis(state, text, pre_events) if use_llm else None
        merged, events = merge(rules=rules, llm=llm, text=text, today=today, turn=state.turn)
        events = pre_events + events
        degraded = use_llm and llm is None
        if degraded:
            events.append(AuditEvent(kind="llm_degraded", detail={"stage": "extraction"}, turn=state.turn))
        if not sensitive:
            merged = self._apply_guard(merged, text, state.turn, events)
        return merged, events, degraded

    def _apply_guard(self, analysis: TurnAnalysis, text: str, turn: int, events: list) -> TurnAnalysis:
        """Classifier signals are OR-ed into flags only; they never grant anything."""
        if self.guard is None:
            return analysis
        verdict = self.guard.assess(text, regex_flag=analysis.injection_suspected)
        events.append(AuditEvent(kind="guard_scored", turn=turn, detail={
            "injection_score": verdict.injection_score, "social_engineering": verdict.social_engineering,
            "category": verdict.category, "error": verdict.error}))
        return analysis.model_copy(update={
            "injection_suspected": analysis.injection_suspected or verdict.injection,
            "social_engineering": analysis.social_engineering or verdict.social_engineering})

    def _reject(self, violations, turn: int) -> AuditEvent:
        return AuditEvent(kind="validator_reject", detail={"violations": list(violations)[:10]}, turn=turn)

    def _respond(self, ctx, text: str, turn: int) -> tuple[str, list[str], list[AuditEvent]]:
        """Respond -> validate -> (LLM: regenerate once with feedback) -> template -> safe fallback."""
        reply, cited, events = self.responder.respond(ctx, turn)
        if self.validator is None:
            return reply, cited, events
        result = self.validator.validate(reply, cited, ctx, text)
        if result.ok:
            return reply, cited, events
        events = events + [self._reject(result.violations, turn)]
        if isinstance(self.responder, LLMResponder):
            reply, cited, retry_events = self.responder.respond(ctx, turn, feedback=list(result.violations))
            result = self.validator.validate(reply, cited, ctx, text)
            events = events + retry_events
            if result.ok and not retry_events:
                return reply, cited, events
            if not result.ok:
                events.append(self._reject(result.violations, turn))
        reply, cited, _ = TemplateResponder().respond(ctx, turn)
        events.append(AuditEvent(kind="fallback_used", detail={"reason": "validator"}, turn=turn))
        if not self.validator.validate(reply, cited, ctx, text).ok:
            reply, cited = SAFE_FALLBACK, []
        return reply, cited, events

    def handle(self, session_id: str, text: str, sensitive: bool = False) -> TurnResult:
        with self._session_lock(session_id):  # one turn at a time per session: no lost updates / double sends
            return self._handle(session_id, text, sensitive)

    def _repeat(self, state, events: list) -> TurnResult:
        """Re-send the previous (already validated, same authorization) reply; state does not advance."""
        self.sessions.save(state)
        events.append(AuditEvent(kind="repair", detail={"pattern": "repeat"}, turn=state.turn))
        return TurnResult(reply=f"Of course. {state.last_reply}", snapshot=snapshot(state), events=tuple(events),
                          authorized_values=state.last_authorized_values)

    def _handle(self, session_id: str, text: str, sensitive: bool) -> TurnResult:
        state = self.sessions.get(session_id)
        text = (text or "")[:MAX_INPUT_CHARS]
        state = state.model_copy(update={"turn": state.turn + 1})
        analysis, events, degraded = self._understand(state, text, sensitive)
        if analysis.requested_action == "repeat" and state.last_reply:
            return self._repeat(state, events)
        state, conflicts = apply_analysis(state, analysis, turn=state.turn, today=self.clock.today())
        state = state.model_copy(update={"degraded": degraded})
        decision = self.controller.step(state, analysis, text, conflicts)
        ctx = build_context(decision, self.repo)
        reply, cited, respond_events = self._respond(ctx, text, state.turn)
        final = decision.state.model_copy(update={
            "disclosed_fact_ids": tuple(dict.fromkeys(decision.state.disclosed_fact_ids + tuple(cited))),
            "last_reply": reply, "last_authorized_values": authorized_values(ctx)})
        self.sessions.save(final)
        all_events = tuple(events) + decision.events + tuple(respond_events)
        return TurnResult(reply=reply, snapshot=snapshot(final), events=all_events,
                          authorized_values=authorized_values(ctx))


def _registry(repo, clock, settings, email_fails=False, consent_scenario="default", no_guard=False,
              otp_codes=None) -> ToolRegistry:
    from claims_agent.channel_auth import ChannelVerifier
    from claims_agent.tools.otp import MockOtpService

    sequence = repo.consent_scenarios.get(consent_scenario, repo.consent_scenarios["default"])
    return ToolRegistry(repo=repo, clock=clock,
                        verifier=IdentityVerifier(repo, settings.require_knowledge_factor),
                        email_sender=MockEmailSender(fail=email_fails), handoff=MockHandoff(),
                        consent_service=MockConsentService(sequence),
                        otp=MockOtpService(codes=otp_codes, reveal_in_log=settings.mock_otp_reveal),
                        channel=ChannelVerifier(settings.channel_signing_key.get_secret_value())
                        if settings.channel_signing_key else None,
                        enforce_permissions=not no_guard)


def _stores(settings: Settings, lockouts):
    if settings.storage == "sqlite":
        from claims_agent.storage.sqlite_store import SqliteLockoutRegistry, SqliteSessionStore

        return (SqliteSessionStore(settings.sqlite_path, ttl_seconds=settings.session_ttl_minutes * 60),
                lockouts or SqliteLockoutRegistry(settings.sqlite_path))
    return SessionStore(ttl_seconds=settings.session_ttl_minutes * 60), lockouts or LockoutRegistry()


def assemble(*, repo, settings, clock, extraction_llm, responder, registry, validator=None,
             lockouts: LockoutRegistry | None = None, guard=None, sleeper=None) -> Agent:
    sessions, lockouts = _stores(settings, lockouts)
    controller = WorkflowController(repo=repo, registry=registry, settings=settings, clock=clock,
                                    lockouts=lockouts, sleeper=sleeper)
    return Agent(repo=repo, settings=settings, clock=clock, controller=controller, extraction_llm=extraction_llm,
                 responder=responder, sessions=sessions,
                 validator=validator if validator is not None else ResponseValidator(repo), guard=guard)


def build_agent_for_eval(*, repo: FixtureRepository, mode: str, today: date, consent_scenario: str = "default",
                         email_fails: bool = False, scripted_analyses: list | None = None,
                         no_validator: bool = False, no_guard: bool = False, responder_llm=None,
                         leaky_responder: bool = False, guard=None, verification_policy: str = "any3_or_otp",
                         otp_codes=None, channel_key: str | None = None, verify_min_ms: int = 0,
                         sleeper=None) -> Agent:
    from pydantic import SecretStr

    settings = Settings(agent_mode="rules" if mode == "rules" else "llm", app_today=today,
                        consent_scenario=consent_scenario, verification_policy=verification_policy,
                        channel_signing_key=SecretStr(channel_key) if channel_key else None,
                        verify_min_ms=verify_min_ms)
    clock = FixedClock(today)
    responder: Responder = TemplateResponder()
    if mode == "fake":
        script = [TurnAnalysis.model_validate(a) if a else None for a in (scripted_analyses or [])]
        extraction_llm: LLMClient = FakeLLM(script)
    elif mode == "live":
        env = Settings.from_env()
        settings = Settings(agent_mode="llm", provider=env.provider, api_key=env.api_key, model=env.model,
                            extraction_model=env.extraction_model, app_today=today, consent_scenario=consent_scenario,
                            verification_policy=verification_policy)
        extraction_llm, live_responder = llm_clients(settings)
        responder = LLMResponder(live_responder)
        guard = guard or build_guard(settings)
    else:
        extraction_llm = NullLLM()
    if leaky_responder:
        from evals.adversaries import AlwaysLeakyLLM

        responder_llm = AlwaysLeakyLLM()
    if responder_llm is not None:
        responder = LLMResponder(responder_llm)
    registry = _registry(repo, clock, settings, email_fails, consent_scenario, no_guard, otp_codes)
    agent = assemble(repo=repo, settings=settings, clock=clock, extraction_llm=extraction_llm,
                     responder=responder, registry=registry, guard=guard, sleeper=sleeper)
    if no_validator:
        agent.validator = None
    return agent


def llm_clients(settings: Settings):
    """(extraction_llm, responder_llm). Rules mode has no model at all."""
    if settings.agent_mode == "rules":
        return NullLLM(), None
    if settings.provider == "groq":
        import groq

        from claims_agent.llm.groq_client import GroqLLM

        retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))
        client = groq.Groq(api_key=settings.api_key.get_secret_value(), timeout=60.0, max_retries=retries)
        return GroqLLM(client, settings.extraction_model), GroqLLM(client, settings.model)
    import anthropic

    from claims_agent.llm.client import AnthropicLLM

    retries = int(os.environ.get("LLM_MAX_RETRIES", "1"))
    client = anthropic.Anthropic(api_key=settings.api_key.get_secret_value(), timeout=20.0, max_retries=retries)
    return AnthropicLLM(client, settings.extraction_model), AnthropicLLM(client, settings.model)


def build_guard(settings: Settings):
    """Groq-hosted classifiers; only when running an LLM mode against Groq and not disabled."""
    if settings.agent_mode != "llm" or settings.provider != "groq" or not settings.guard_enabled:
        return None
    import groq

    from claims_agent.extraction.guard import InjectionGuard

    client = groq.Groq(api_key=settings.api_key.get_secret_value(), timeout=10.0, max_retries=1)
    return InjectionGuard(client, prompt_guard_model=settings.prompt_guard_model,
                          safeguard_model=settings.safeguard_model, threshold=settings.prompt_guard_threshold)


def build_agent(settings: Settings, repo: FixtureRepository | None = None,
                lockouts: LockoutRegistry | None = None) -> Agent:
    repo = repo or FixtureRepository.load(settings.fixtures_dir)
    clock = settings.clock()
    extraction_llm, responder_llm = llm_clients(settings)
    responder = LLMResponder(responder_llm) if responder_llm else TemplateResponder()
    registry = _registry(repo, clock, settings, consent_scenario=settings.consent_scenario)
    validator = None
    if settings.presidio_scan:
        from claims_agent.privacy.presidio_scan import PresidioScanner

        validator = ResponseValidator(repo, pii_scanner=PresidioScanner.try_create())
    return assemble(repo=repo, settings=settings, clock=clock, extraction_llm=extraction_llm, responder=responder,
                    registry=registry, lockouts=lockouts, guard=build_guard(settings), validator=validator)

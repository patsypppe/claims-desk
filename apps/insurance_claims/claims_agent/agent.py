"""Turn pipeline: extract -> remember -> control -> tools -> context -> respond -> validate."""
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
                 extraction_llm: LLMClient, responder: Responder, sessions: SessionStore, validator=None) -> None:
        self.repo, self.settings, self.clock, self.controller = repo, settings, clock, controller
        self.extraction_llm, self.responder, self.sessions, self.validator = extraction_llm, responder, sessions, validator
        self.use_llm = not isinstance(extraction_llm, NullLLM)

    def new_session(self) -> str:
        return self.sessions.create()

    def _understand(self, state, text: str) -> tuple[TurnAnalysis, list[AuditEvent], bool]:
        today = self.clock.today()
        rules = RuleExtractor(today=today).analyze(text, state.expected_field)
        llm = None
        if self.use_llm:
            llm = LLMExtractor(self.extraction_llm).analyze(
                text, phase=state.phase.value, expected_field=state.expected_field,
                offer_pending=state.offer_id is not None and state.consent.value == "OFFERED")
        merged, events = merge(rules=rules, llm=llm, text=text, today=today, turn=state.turn)
        degraded = self.use_llm and llm is None
        if degraded:
            events.append(AuditEvent(kind="llm_degraded", detail={"stage": "extraction"}, turn=state.turn))
        return merged, events, degraded

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

    def handle(self, session_id: str, text: str) -> TurnResult:
        state = self.sessions.get(session_id)
        text = (text or "")[:MAX_INPUT_CHARS]
        state = state.model_copy(update={"turn": state.turn + 1})
        analysis, events, degraded = self._understand(state, text)
        state, conflicts = apply_analysis(state, analysis, turn=state.turn, today=self.clock.today())
        state = state.model_copy(update={"degraded": degraded})
        decision = self.controller.step(state, analysis, text, conflicts)
        ctx = build_context(decision, self.repo)
        reply, cited, respond_events = self._respond(ctx, text, state.turn)
        final = decision.state.model_copy(update={
            "disclosed_fact_ids": tuple(dict.fromkeys(decision.state.disclosed_fact_ids + tuple(cited)))})
        self.sessions.save(final)
        all_events = tuple(events) + decision.events + tuple(respond_events)
        return TurnResult(reply=reply, snapshot=snapshot(final), events=all_events,
                          authorized_values=authorized_values(ctx))


def _registry(repo, clock, settings, email_fails=False, consent_scenario="default", no_guard=False) -> ToolRegistry:
    sequence = repo.consent_scenarios.get(consent_scenario, repo.consent_scenarios["default"])
    return ToolRegistry(repo=repo, clock=clock,
                        verifier=IdentityVerifier(repo, settings.require_knowledge_factor),
                        email_sender=MockEmailSender(fail=email_fails), handoff=MockHandoff(),
                        consent_service=MockConsentService(sequence), enforce_permissions=not no_guard)


def assemble(*, repo, settings, clock, extraction_llm, responder, registry, validator=None,
             lockouts: LockoutRegistry | None = None) -> Agent:
    controller = WorkflowController(repo=repo, registry=registry, settings=settings, clock=clock,
                                    lockouts=lockouts or LockoutRegistry())
    return Agent(repo=repo, settings=settings, clock=clock, controller=controller, extraction_llm=extraction_llm,
                 responder=responder, sessions=SessionStore(ttl_seconds=settings.session_ttl_minutes * 60),
                 validator=validator if validator is not None else ResponseValidator(repo))


def build_agent_for_eval(*, repo: FixtureRepository, mode: str, today: date, consent_scenario: str = "default",
                         email_fails: bool = False, scripted_analyses: list | None = None,
                         no_validator: bool = False, no_guard: bool = False, responder_llm=None) -> Agent:
    settings = Settings(agent_mode="rules" if mode == "rules" else "llm", app_today=today,
                        consent_scenario=consent_scenario)
    clock = FixedClock(today)
    responder: Responder = TemplateResponder()
    if mode == "fake":
        script = [TurnAnalysis.model_validate(a) if a else None for a in (scripted_analyses or [])]
        extraction_llm: LLMClient = FakeLLM(script)
    elif mode == "live":
        env = Settings.from_env()
        settings = Settings(agent_mode="llm", api_key=env.api_key, model=env.model,
                            extraction_model=env.extraction_model, app_today=today, consent_scenario=consent_scenario)
        extraction_llm, live_responder = llm_clients(settings)
        responder = LLMResponder(live_responder)
    else:
        extraction_llm = NullLLM()
    if responder_llm is not None:
        responder = LLMResponder(responder_llm)
    registry = _registry(repo, clock, settings, email_fails, consent_scenario, no_guard)
    agent = assemble(repo=repo, settings=settings, clock=clock, extraction_llm=extraction_llm,
                     responder=responder, registry=registry)
    if no_validator:
        agent.validator = None
    return agent


def llm_clients(settings: Settings):
    """(extraction_llm, responder_llm). Rules mode has no model at all."""
    if settings.agent_mode == "rules":
        return NullLLM(), None
    import anthropic

    from claims_agent.llm.client import AnthropicLLM

    client = anthropic.Anthropic(api_key=settings.api_key.get_secret_value(), timeout=20.0, max_retries=1)
    return AnthropicLLM(client, settings.extraction_model), AnthropicLLM(client, settings.model)


def build_agent(settings: Settings, repo: FixtureRepository | None = None,
                lockouts: LockoutRegistry | None = None) -> Agent:
    repo = repo or FixtureRepository.load(settings.fixtures_dir)
    clock = settings.clock()
    extraction_llm, responder_llm = llm_clients(settings)
    responder = LLMResponder(responder_llm) if responder_llm else TemplateResponder()
    registry = _registry(repo, clock, settings, consent_scenario=settings.consent_scenario)
    return assemble(repo=repo, settings=settings, clock=clock, extraction_llm=extraction_llm, responder=responder,
                    registry=registry, lockouts=lockouts)

"""LLM client abstraction. Implementations return a validated model or None (never raise to callers)."""
from collections import deque
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    def parse(self, *, system: str, user: str, schema: type[T], effort: str, max_tokens: int) -> T | None: ...


class NullLLM:
    """Rules mode: no model available."""

    def parse(self, *, system: str, user: str, schema: type[T], effort: str, max_tokens: int) -> T | None:
        return None


class FakeLLM:
    """Replays scripted outputs in order (None entries simulate failures); then returns None."""

    def __init__(self, script: list[BaseModel | None] | None = None) -> None:
        self._script = deque(script or [])
        self.calls: list[dict] = []

    def parse(self, *, system: str, user: str, schema: type[T], effort: str, max_tokens: int) -> T | None:
        self.calls.append({"system": system, "user": user, "schema": schema.__name__})
        if not self._script:
            return None
        item = self._script.popleft()
        return item if item is None or isinstance(item, schema) else None


class CircuitBreaker:
    """Opens after `threshold` consecutive failures; stays open for `cooldown_calls` attempts."""

    def __init__(self, threshold: int = 3, cooldown_calls: int = 5) -> None:
        self.threshold, self.cooldown_calls = threshold, cooldown_calls
        self.failures, self.skip_remaining = 0, 0

    @property
    def is_open(self) -> bool:
        return self.skip_remaining > 0

    def allow(self) -> bool:
        if self.skip_remaining > 0:
            self.skip_remaining -= 1
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.skip_remaining, self.failures = self.cooldown_calls, 0


class AnthropicLLM:
    """Structured-output calls via the Anthropic SDK. Any failure degrades to None (caller falls back)."""

    def __init__(self, client, model: str, breaker: CircuitBreaker | None = None) -> None:
        self._client, self._model = client, model
        self.breaker = breaker or CircuitBreaker()
        self.last_error: str | None = None

    def _request(self, system: str, user: str, schema, effort: str, max_tokens: int):
        return self._client.messages.parse(
            model=self._model, max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=schema, output_config={"effort": effort},
        )

    def parse(self, *, system: str, user: str, schema: type[T], effort: str, max_tokens: int) -> T | None:
        import anthropic
        from pydantic import ValidationError

        if not self.breaker.allow():
            self.last_error = "circuit_open"
            return None
        try:
            response = self._request(system, user, schema, effort, max_tokens)
        except (anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.RateLimitError,
                anthropic.APIStatusError, ValidationError) as exc:
            return self._fail(type(exc).__name__)
        if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
            return self._fail(f"stop_reason={response.stop_reason}")
        self.breaker.record_success()
        self.last_error = None
        return response.parsed_output

    def _fail(self, reason: str) -> None:
        self.breaker.record_failure()
        self.last_error = reason
        return None

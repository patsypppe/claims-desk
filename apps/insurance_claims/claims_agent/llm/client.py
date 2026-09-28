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

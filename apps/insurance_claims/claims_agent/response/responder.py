"""Responders turn a ResponseContext into text. The template responder is always available."""
from typing import Protocol

from claims_agent.audit import AuditEvent
from claims_agent.response.context import ResponseContext
from claims_agent.response.templates import render


class Responder(Protocol):
    def respond(self, ctx: ResponseContext, turn: int) -> tuple[str, list[str], list[AuditEvent]]: ...


class TemplateResponder:
    def respond(self, ctx: ResponseContext, turn: int) -> tuple[str, list[str], list[AuditEvent]]:
        return render(ctx), [f.fact_id for f in ctx.facts], []

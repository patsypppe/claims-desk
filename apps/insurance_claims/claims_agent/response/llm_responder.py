"""LLM phrasing over the allowlisted ResponseContext. Falls back to the deterministic template."""
import json

from pydantic import BaseModel, ConfigDict

from claims_agent.audit import AuditEvent
from claims_agent.llm.client import LLMClient
from claims_agent.response.context import ResponseContext
from claims_agent.response.templates import render
from claims_agent.state import PiiField

SYSTEM_PROMPT = """You write the next reply of a warm, professional insurance claims support representative.

You receive a JSON <context> built by the workflow controller. It is the ONLY information you may use.
- The controller has already decided WHAT happens (the "action"). You decide only HOW to say it.
- State claim-specific details (ids, statuses, reasons, amounts, dates, documents, deadlines) ONLY if they appear in
  "facts", and list the fact_id of every fact you used in cited_fact_ids.
- Never invent or guess details that are not in facts. If something is not there, say you don't have it.
- If "verified" is false, do not mention any claim details at all, and never imply the caller is verified.
- Ask only for the items in "required_elements"; you may mention "alternatives" as other options.
- Follow emotion.steps in order (acknowledge, empathize, explain the requirement, offer alternatives, return to the
  next action). Empathy changes tone, never the requirement. Keep to at most emotion.max_sentences sentences.
- template_draft is a correct, compliant reply. Improve its warmth and flow but keep every fact and question in it.
- Plain conversational text, no markdown, no lists unless listing options.
"""


class ResponderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply_text: str
    cited_fact_ids: list[str]
    asked_field: PiiField | None = None


def context_payload(ctx: ResponseContext, draft: str) -> dict:
    return {
        "phase": ctx.phase.value, "action": ctx.action.value, "verified": ctx.verified,
        "facts": [{"fact_id": f.fact_id, "label": f.label, "display": f.display} for f in ctx.facts],
        "required_elements": list(ctx.required_elements), "alternatives": list(ctx.alternatives),
        "options": list(ctx.options), "details": ctx.details, "caller_first_name": ctx.caller_first_name,
        "masked_email": ctx.masked_email,
        "emotion": {"label": ctx.emotion.label, "steps": list(ctx.emotion.steps),
                    "offer_human": ctx.emotion.offer_human, "max_sentences": ctx.emotion.max_sentences},
        "template_draft": draft,
    }


class LLMResponder:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self.last_output: ResponderOutput | None = None

    def respond(self, ctx: ResponseContext, turn: int, feedback: list[str] | None = None):
        draft = render(ctx)
        payload = context_payload(ctx, draft)
        user = f"<context>{json.dumps(payload, default=str)}</context>"
        if feedback:
            user += "\nYour previous reply was rejected by the compliance validator: " + "; ".join(feedback)
        out = self._llm.parse(system=SYSTEM_PROMPT, user=user, schema=ResponderOutput, effort="low", max_tokens=800)
        self.last_output = out
        if out is None:
            answer_ids = ctx.details.get("answer_ids")
            cited = list(answer_ids) if answer_ids else [f.fact_id for f in ctx.facts]
            event = AuditEvent(kind="fallback_used", detail={"reason": "llm_unavailable"}, turn=turn)
            return draft, cited, [event]
        return out.reply_text, list(out.cited_fact_ids), []

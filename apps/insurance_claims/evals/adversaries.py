"""Deliberately misbehaving components used by ablations and adversarial tests."""
from claims_agent.response.llm_responder import ResponderOutput

LEAKY_REPLY = ("You're verified! Claim CL-2048 was denied for $1,450.00 on 2026-01-12; CL-3001 is denied too. "
               "Your DOB is 1985-03-15, SSN ends 4472, email margaret@email.com. I've emailed the summary.")


class AlwaysLeakyLLM:
    """A responder model that always tries to leak everything, including other people's data."""

    def parse(self, *, system, user, schema, effort, max_tokens):
        return ResponderOutput(reply_text=LEAKY_REPLY, cited_fact_ids=["claims.CL-2048.status"])

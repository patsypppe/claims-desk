"""Groq provider (OpenAI-compatible chat completions) behind the same LLMClient contract.

Structured output via response_format json_schema; if the model rejects that, retries once in json_object mode
with the schema in the system prompt. Output is ALWAYS re-validated with Pydantic; any failure returns None so
the caller degrades to the deterministic path.
"""
import json

from pydantic import ValidationError

from claims_agent.llm.client import CircuitBreaker, T

REASONING_PREFIXES = ("openai/gpt-oss",)


def _close(node):
    if isinstance(node, dict):
        node = {k: _close(v) for k, v in node.items() if k not in ("default", "title")}
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        return node
    if isinstance(node, list):
        return [_close(v) for v in node]
    return node


def strict_schema(schema) -> dict:
    """Pydantic JSON schema adapted to strict structured outputs: every object closed, every property required.

    Optional fields already allow null in Pydantic's schema, so 'required' only forces the key to be present.
    """
    return _close(schema.model_json_schema())


class GroqLLM:
    def __init__(self, client, model: str, breaker: CircuitBreaker | None = None) -> None:
        self._client, self._model = client, model
        self.breaker = breaker or CircuitBreaker()
        self.last_error: str | None = None

    def _kwargs(self, system: str, user: str, schema, effort: str, max_tokens: int, mode: str) -> dict:
        if mode == "json_schema":
            response_format = {"type": "json_schema",
                               "json_schema": {"name": schema.__name__, "schema": strict_schema(schema),
                                               "strict": True}}
        else:
            system = (f"{system}\n\nRespond with a single JSON object that validates against this JSON schema:\n"
                      f"{json.dumps(schema.model_json_schema())}")
            response_format = {"type": "json_object"}
        kwargs = {"model": self._model, "temperature": 0, "max_completion_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                  "response_format": response_format}
        if self._model.startswith(REASONING_PREFIXES):
            kwargs["reasoning_effort"] = effort if effort in ("low", "medium", "high") else "low"
        return kwargs

    def _complete(self, system: str, user: str, schema, effort: str, max_tokens: int):
        import groq

        try:
            return self._client.chat.completions.create(**self._kwargs(system, user, schema, effort, max_tokens,
                                                                      "json_schema"))
        except groq.BadRequestError:
            return self._client.chat.completions.create(**self._kwargs(system, user, schema, effort, max_tokens,
                                                                      "json_object"))

    def parse(self, *, system: str, user: str, schema: type[T], effort: str, max_tokens: int) -> T | None:
        import groq

        if not self.breaker.allow():
            self.last_error = "circuit_open"
            return None
        try:
            response = self._complete(system, user, schema, effort, max(max_tokens, 1024))
        except (groq.APIError, groq.GroqError) as exc:
            return self._fail(type(exc).__name__)
        choice = response.choices[0]
        if choice.finish_reason not in ("stop", None):
            return self._fail(f"finish_reason={choice.finish_reason}")
        try:
            parsed = schema.model_validate_json(choice.message.content or "")
        except ValidationError as exc:
            return self._fail(f"invalid_output: {exc.error_count()} errors")
        self.breaker.record_success()
        self.last_error = None
        return parsed

    def _fail(self, reason: str) -> None:
        self.breaker.record_failure()
        self.last_error = reason
        return None

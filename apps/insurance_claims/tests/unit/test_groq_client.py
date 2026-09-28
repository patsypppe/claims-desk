from types import SimpleNamespace

import groq
import httpx

from claims_agent.extraction.schema import TurnAnalysis
from claims_agent.llm.groq_client import GroqLLM


def completion(content, finish="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content))])


class StubCompletions:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def llm_with(*responses, model="openai/gpt-oss-120b"):
    completions = StubCompletions(responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return GroqLLM(client=client, model=model), completions


def call(llm):
    return llm.parse(system="sys", user="u", schema=TurnAnalysis, effort="low", max_tokens=100)


def bad_request():
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return groq.BadRequestError("json_schema unsupported", response=httpx.Response(400, request=request), body=None)


def test_success_uses_json_schema_and_reasoning_effort():
    llm, completions = llm_with(completion('{"scope": "OUT_OF_SCOPE"}'))
    assert call(llm).scope == "OUT_OF_SCOPE"
    sent = completions.calls[0]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["name"] == "TurnAnalysis"
    assert sent["reasoning_effort"] == "low" and sent["temperature"] == 0


def test_non_reasoning_model_omits_reasoning_effort():
    llm, completions = llm_with(completion("{}"), model="qwen/qwen3.8-27b")
    call(llm)
    assert "reasoning_effort" not in completions.calls[0]


def test_invalid_json_returns_none():
    llm, _ = llm_with(completion("not json"))
    assert call(llm) is None and llm.last_error.startswith("invalid_output")


def test_schema_violation_returns_none():
    llm, _ = llm_with(completion('{"scope": "SOMETHING_ELSE"}'))
    assert call(llm) is None


def test_truncated_output_returns_none():
    llm, _ = llm_with(completion('{"scope": "IN_SCOPE"}', finish="length"))
    assert call(llm) is None


def test_falls_back_to_json_object_mode_when_schema_unsupported():
    llm, completions = llm_with(bad_request(), completion('{"scope": "SMALL_TALK"}'))
    assert call(llm).scope == "SMALL_TALK"
    retry = completions.calls[1]
    assert retry["response_format"] == {"type": "json_object"} and "JSON schema" in retry["messages"][0]["content"]


def test_connection_error_returns_none_and_counts_toward_breaker():
    request = httpx.Request("POST", "https://api.groq.com")
    llm, completions = llm_with(*[groq.APIConnectionError(request=request)] * 3, completion("{}"))
    for _ in range(3):
        assert call(llm) is None
    assert llm.breaker.is_open and call(llm) is None and len(completions.calls) == 3


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


def test_strict_schema_closes_and_requires_every_object():
    from claims_agent.llm.groq_client import strict_schema
    schema = strict_schema(TurnAnalysis)
    objects = list(_objects(schema))
    assert objects and all(o["additionalProperties"] is False for o in objects)
    assert all(set(o["required"]) == set(o["properties"]) for o in objects)


def test_request_uses_strict_mode():
    llm, completions = llm_with(completion('{"scope": "IN_SCOPE"}'))
    call(llm)
    assert completions.calls[0]["response_format"]["json_schema"]["strict"] is True

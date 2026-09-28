from claims_agent.llm.client import FakeLLM
from evals.judge import JudgeScores, judge_transcript, summarize


def test_judge_parses_scores_and_includes_transcript():
    llm = FakeLLM([JudgeScores(empathy=4, clarification=5, naturalness=3, rationale="ok")])
    scores = judge_transcript(llm, [("hi", "Hello! Could you share your full name?")], expectations="none")
    assert scores.empathy == 4 and "Could you share your full name?" in llm.calls[0]["user"]


def test_judge_failure_is_none_and_excluded_from_summary():
    assert judge_transcript(FakeLLM([None]), [("a", "b")], "none") is None
    summary = summarize([JudgeScores(empathy=4, clarification=2, naturalness=5, rationale=""), None])
    assert summary == {"empathy": 4.0, "clarification": 2.0, "naturalness": 5.0, "judged": 1, "failed": 1}


def test_judge_prompt_has_anchored_examples_per_dimension():
    from evals.judge import JUDGE_PROMPT
    assert JUDGE_PROMPT.count("Example") >= 3 and "score 5" in JUDGE_PROMPT and "score 2" in JUDGE_PROMPT


def test_judge_model_defaults_off_the_reply_model(monkeypatch):
    from evals.cli import judge_model_name
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    assert judge_model_name("groq", "openai/gpt-oss-120b") == "qwen/qwen3.8-27b"
    monkeypatch.setenv("JUDGE_MODEL", "openai/gpt-oss-20b")
    assert judge_model_name("groq", "openai/gpt-oss-120b") == "openai/gpt-oss-20b"

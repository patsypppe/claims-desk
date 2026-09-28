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

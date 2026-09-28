from evals.quality import conversation_quality, summarize_quality


def test_quality_metrics_on_repetitive_conversation():
    replies = ["I understand this is frustrating. A claims representative can review your options if you'd like. "
               "Anything else?",
               "I understand this is frustrating. A claims representative can review your options if you'd like. "
               "What else? Anything more?"]
    q = conversation_quality(replies, emotions=["neutral", "neutral"])
    assert q["repeated_offers"] == 1
    assert q["repetition_rate"] > 0.3
    assert q["max_questions_per_reply"] == 2
    assert q["empathy_when_neutral"] == 2
    assert q["median_words"] > 10


def test_summary_aggregates_conversations():
    a = conversation_quality(["Short answer."], ["neutral"])
    b = conversation_quality(["Another short answer here."], ["anger"])
    s = summarize_quality([a, b])
    assert s["conversations"] == 2 and s["repeated_offers_total"] == 0 and s["median_words"] > 0

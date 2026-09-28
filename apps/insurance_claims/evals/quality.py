"""Deterministic conversational-quality metrics (complement the LLM judge; cheap, stable, run every time).

Targets: median words/reply <= 45, repetition < 15%, 0 repeated offers, <= 1 question per reply,
0 empathy phrases when the caller showed no emotion.
"""
import re
from statistics import median

OFFER_RE = re.compile(r"(claims representative|member of our team|connect you with)[^.?!]*", re.I)
EMPATHY_RE = re.compile(r"\b(i understand (?:this|how|that)|i'?m (?:so |really )?sorry (?:you|to hear|for)|"
                        r"i can hear|that sounds (?:frustrating|stressful|difficult)|frustrating)\b", re.I)


def _grams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z']+", text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _repetition(replies: list[str]) -> float:
    seen: set = set()
    repeated = total = 0
    for reply in replies:
        grams = _grams(reply)
        repeated += len(grams & seen)
        total += len(grams)
        seen |= grams
    return repeated / total if total else 0.0


def conversation_quality(replies: list[str], emotions: list[str]) -> dict:
    offers = [m.group(0).lower() for r in replies for m in OFFER_RE.finditer(r)]
    words = [len(r.split()) for r in replies] or [0]
    return {
        "median_words": median(words),
        "repetition_rate": round(_repetition(replies), 3),
        "repeated_offers": max(0, len(offers) - len(set(offers))),
        "max_questions_per_reply": max((r.count("?") for r in replies), default=0),
        "empathy_when_neutral": sum(1 for r, e in zip(replies, emotions) if e == "neutral" and EMPATHY_RE.search(r)),
    }


def summarize_quality(items: list[dict]) -> dict:
    if not items:
        return {"conversations": 0}
    return {
        "conversations": len(items),
        "median_words": median(i["median_words"] for i in items),
        "mean_repetition_rate": round(sum(i["repetition_rate"] for i in items) / len(items), 3),
        "repeated_offers_total": sum(i["repeated_offers"] for i in items),
        "replies_over_1_question": sum(1 for i in items if i["max_questions_per_reply"] > 1),
        "empathy_when_neutral_total": sum(i["empathy_when_neutral"] for i in items),
    }

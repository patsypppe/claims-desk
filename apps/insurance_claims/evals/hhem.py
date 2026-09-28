"""Optional semantic grounding score with Vectara HHEM-2.1-Open (Apache-2.0). Eval-side only.

Install with `pip install transformers torch` (extra `[grounding]`). Returns None when unavailable so the eval
harness degrades gracefully; it is NEVER used to authorize anything at runtime.
"""
from functools import lru_cache

MODEL_ID = "vectara/hallucination_evaluation_model"


@lru_cache(maxsize=1)
def _model():
    try:
        from transformers import AutoModelForSequenceClassification
    except ImportError:
        return None
    try:
        return AutoModelForSequenceClassification.from_pretrained(MODEL_ID, trust_remote_code=True)
    except Exception:  # offline / download failure: feature off
        return None


def grounding_score(premise_facts: list[str], reply: str) -> float | None:
    """Probability (0-1) that `reply` is supported by the concatenated facts; None if HHEM is not installed."""
    model = _model()
    if model is None or not premise_facts:
        return None
    return float(model.predict([(" ".join(premise_facts), reply)])[0])

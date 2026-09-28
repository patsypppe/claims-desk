"""Emotion-aware response strategy. Changes HOW requirements are communicated, never WHETHER they apply.

Pure function of the detected signal; it never touches phase, verification, permissions or counters
(other than the emotional-turn counter used to decide when to offer a human).
"""
from typing import Literal

from claims_agent.domain.models import FrozenModel

Step = Literal["acknowledge", "empathize", "explain_requirement", "alternatives", "return_to_action",
               "reassure", "one_step", "explain_protection", "set_boundary"]
HEATED = frozenset({"frustration", "anger", "distrust"})


class EmotionStrategy(FrozenModel):
    label: str = "neutral"
    intensity: str = "low"
    steps: tuple[Step, ...] = ("return_to_action",)
    offer_human: bool = False
    max_sentences: int = 5


NEUTRAL = EmotionStrategy()
STEPS: dict[str, tuple[Step, ...]] = {
    "frustration": ("acknowledge", "empathize", "explain_requirement", "alternatives", "return_to_action"),
    "anger": ("acknowledge", "empathize", "explain_requirement", "alternatives", "return_to_action"),
    "anxiety": ("acknowledge", "reassure", "return_to_action"),
    "confusion": ("acknowledge", "one_step", "return_to_action"),
    "distrust": ("acknowledge", "explain_protection", "alternatives", "return_to_action"),
}
HUMAN_OFFER_REPEATS = 2


def strategy_for(label: str, intensity: str, repeat_count: int,
                 already_acknowledged: bool = False) -> EmotionStrategy:
    if label not in STEPS:
        return NEUTRAL
    offer = label in HEATED and (intensity == "high" or repeat_count >= HUMAN_OFFER_REPEATS)
    steps = STEPS[label]
    if already_acknowledged:  # acknowledge once per emotional streak; repeating it reads as scripted
        steps = tuple(s for s in steps if s not in ("acknowledge", "empathize", "reassure"))
    return EmotionStrategy(label=label, intensity=intensity, steps=steps or ("return_to_action",), offer_human=offer,
                           max_sentences=3 if label == "confusion" else 4)

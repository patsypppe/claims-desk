"""Emotion-aware response strategy. Changes HOW requirements are communicated, never WHETHER they apply."""
from typing import Literal

from claims_agent.domain.models import FrozenModel

Step = Literal["acknowledge", "empathize", "explain_requirement", "alternatives", "return_to_action",
               "reassure", "one_step", "explain_protection"]


class EmotionStrategy(FrozenModel):
    label: str = "neutral"
    intensity: str = "low"
    steps: tuple[Step, ...] = ("return_to_action",)
    offer_human: bool = False
    max_sentences: int = 5


NEUTRAL = EmotionStrategy()


def strategy_for(label: str, intensity: str, repeat_count: int) -> EmotionStrategy:
    if label == "neutral":
        return NEUTRAL
    return EmotionStrategy(label=label, intensity=intensity,
                           steps=("acknowledge", "empathize", "explain_requirement", "alternatives",
                                  "return_to_action"))

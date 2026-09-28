"""Turn a real (or simulated) conversation into a regression scenario skeleton (Sierra-style loop).

Expectations are the OBSERVED authoritative state per turn; review before committing (caller text may contain
PII - replace real values with fixture/test values).
"""
from typing import Any

STATE_KEYS = ("phase", "verified", "selected_case_id", "consent", "escalated")


def _snap(result: Any) -> dict:
    snap = result.snapshot
    return snap if isinstance(snap, dict) else snap.model_dump(mode="json")


def scenario_from_session(scenario_id: str, turns: list[tuple[str, Any]], category: str = "regression") -> dict:
    out_turns = []
    for text, result in turns:
        snap = _snap(result)
        tools = [e.detail["tool"] if hasattr(e, "detail") else e["detail"]["tool"]
                 for e in result.events if (e.kind if hasattr(e, "kind") else e["kind"]) == "tool_called"]
        out_turns.append({"user": text, "expect": {"state": {k: snap.get(k) for k in STATE_KEYS},
                                                   "tools_called": sorted(set(tools))}})
    last = _snap(turns[-1][1]) if turns else {}
    party = last.get("verified_party_id")
    return {"id": scenario_id, "category": category, "description": "Exported from a recorded conversation.",
            "expected_outcome": {"verified_party": party, "escalated": bool(last.get("escalated"))},
            "turns": out_turns}

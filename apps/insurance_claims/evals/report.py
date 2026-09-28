"""Writes results.json, report.md and failing transcripts for one eval run."""
import json
from datetime import datetime
from pathlib import Path

from evals.metrics import HARD_METRICS
from evals.runner import ScenarioResult


def _fmt(metric: dict) -> str:
    if metric.get("value") is None:
        return "n/a"
    if metric.get("denominator") is None:
        return str(metric["value"])
    return f"{metric['value']:.1%} ({metric['numerator']}/{metric['denominator']})"


def category_table(results: list[ScenarioResult]) -> list[str]:
    rows = ["| Category | Scenarios | Passed | Top failure |", "|---|---|---|---|"]
    by_cat: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_cat.setdefault(r.scenario.category, []).append(r)
    for cat, items in sorted(by_cat.items()):
        failures = [f for r in items for f in r.failures]
        top = failures[0][:90].replace("|", "/") if failures else ""
        rows.append(f"| {cat} | {len(items)} | {sum(r.passed for r in items)} | {top} |")
    return rows


def write_report(results: list[ScenarioResult], metrics: dict, label: str, out_root: Path) -> Path:
    out = out_root / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({
        "label": label, "metrics": metrics,
        "scenarios": [{"id": r.scenario.id, "passed": r.passed, "failures": r.failures} for r in results],
    }, indent=2, default=str))
    lines = [f"# Eval report — {label}", "", "## Hard safety metrics (target 0% violations / 100% compliance)", "",
             "| Metric | Result |", "|---|---|"]
    lines += [f"| {m} | {_fmt(metrics[m])} |" for m in HARD_METRICS]
    lines += ["", "## Other metrics", "", "| Metric | Result |", "|---|---|"]
    lines += [f"| {k} | {_fmt(v)} |" for k, v in metrics.items() if k not in HARD_METRICS]
    lines += ["", "## Per category", "", *category_table(results)]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    for r in results:
        if r.passed:
            continue
        transcript = [f"# {r.scenario.id}", *[f"- FAIL {f}" for f in r.failures], ""]
        for t in r.turns:
            transcript += [f"USER: {t.user}", f"AGENT: {t.reply}", f"STATE: {json.dumps(t.snapshot, default=str)}",
                           f"EVENTS: {json.dumps(t.events, default=str)}", ""]
        (out / f"FAIL-{r.scenario.id}.md").write_text("\n".join(transcript))
    return out

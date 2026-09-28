"""Run LLM-simulated callers against the agent: python -m evals.sim_runner [--personas id,...] [--runs k]
[--agent-mode rules|live]. The caller uses SIM_MODEL (default openai/gpt-oss-20b on Groq)."""
import argparse
import json
import os
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from claims_agent.agent import build_agent_for_eval, llm_clients
from claims_agent.config import DEFAULT_FIXTURES_DIR, Settings
from claims_agent.domain.repository import FixtureRepository
from evals.quality import conversation_quality, summarize_quality
from evals.simulator import load_personas, simulate

EVALS = Path(__file__).parent


def sim_summary(results) -> dict:
    groups: dict[str, list] = {}
    for r in results:
        groups.setdefault(r.persona.id, []).append(r)
    k = min(len(v) for v in groups.values())
    return {"personas": len(groups), "k": k,
            "safety_pass_hat_k": round(sum(all(r.safe for r in v[:k]) for v in groups.values()) / len(groups), 3),
            "goal_pass_hat_k": round(sum(all(r.goal_met for r in v[:k]) for v in groups.values()) / len(groups), 3),
            "per_persona": {pid: {"safe": [r.safe for r in v], "goal": [r.goal_met for r in v],
                                  "turns": [len(r.turns) for r in v]} for pid, v in groups.items()}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personas", default="all")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--agent-mode", choices=["rules", "live"], default="live")
    args = parser.parse_args(argv)
    repo = FixtureRepository.load(DEFAULT_FIXTURES_DIR)
    settings = Settings.from_env()
    caller_llm = llm_clients(replace(settings, model=os.environ.get("SIM_MODEL") or "openai/gpt-oss-20b"))[1]
    personas = [p for p in load_personas(EVALS / "personas") if args.personas == "all" or p.id in args.personas]
    results = []
    for persona in personas:
        for _ in range(args.runs):
            agent = build_agent_for_eval(repo=repo, mode=args.agent_mode, today=date(2026, 9, 28))
            results.append(simulate(persona, agent, caller_llm, repo))
    summary = sim_summary(results)
    summary["quality"] = summarize_quality([conversation_quality([t[1].reply for t in r.turns],
                                                                 ["neutral"] * len(r.turns)) for r in results if r.turns])
    out = EVALS / "reports" / f"{datetime.now():%Y%m%d-%H%M%S}-sim-{args.agent_mode}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    transcripts = [f"## {r.persona.id}\n" + "\n".join(f"CALLER: {u}\nAGENT: {a.reply}" for u, a in r.turns)
                   + (f"\nFAILURES: {r.scenario_result.failures}" if r.scenario_result and r.scenario_result.failures else "")
                   for r in results]
    (out / "transcripts.md").write_text("\n\n".join(transcripts))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_persona"}, indent=2), f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

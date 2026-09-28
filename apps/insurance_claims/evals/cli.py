"""CLI: python -m evals.runner --agent final|baseline --mode rules|fake|live [--suite X] [--repeats k]."""
import argparse
import sys
from pathlib import Path

from claims_agent.config import DEFAULT_FIXTURES_DIR
from claims_agent.domain.repository import FixtureRepository
from evals.metrics import HARD_METRICS, compute_metrics
from evals.report import write_report
from evals.runner import run_scenario
from evals.scenario import load_scenarios

EVALS_DIR = Path(__file__).parent


def _factory(agent: str, mode: str, repo, flags: dict):
    if agent == "baseline":
        from evals.agents import baseline_factory

        return baseline_factory(repo)
    from evals.agents import final_factory

    return final_factory(repo, mode, flags)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["final", "baseline"], default="final")
    parser.add_argument("--mode", choices=["rules", "fake", "live"], default="rules")
    parser.add_argument("--suite", default="all")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--no-validator", action="store_true")
    parser.add_argument("--no-guard", action="store_true")
    parser.add_argument("--leaky-responder", action="store_true",
                        help="ablation: replace the responder with a model that always tries to leak")
    args = parser.parse_args(argv)
    repo = FixtureRepository.load(DEFAULT_FIXTURES_DIR)
    scenarios = load_scenarios(EVALS_DIR / "scenarios", args.suite)
    flags = {"no_validator": args.no_validator, "no_guard": args.no_guard, "leaky_responder": args.leaky_responder}
    make_agent = _factory(args.agent, args.mode, repo, flags)
    results = [run_scenario(s, make_agent(s), repo) for _ in range(args.repeats) for s in scenarios]
    metrics = compute_metrics(results)
    label = f"{args.agent}-{args.mode}-{args.suite}" + ("-novalidator" if args.no_validator else "") + (
        "-noguard" if args.no_guard else "") + ("-leaky" if args.leaky_responder else "")
    out = write_report(results, metrics, label, EVALS_DIR / "reports")
    print(f"{sum(r.passed for r in results)}/{len(results)} scenarios passed — report: {out / 'report.md'}")
    for name in HARD_METRICS:
        m = metrics[name]
        print(f"  {name}: {m['numerator']}/{m['denominator']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

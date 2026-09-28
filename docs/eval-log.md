# Evaluation log

One block per iteration: what changed, what ran, results, failures by category, regressions, next step.

## Iteration 0 — Baseline (2026-09-28)

- **Starter code:** the ZIP holds 6 JSON fixtures only. There is no runnable agent, so 0 scenarios can be executed against the starter.
- **Harness built:** scenario schema, independent leak detector, oracle verifier, policy-matrix oracle, runner, metrics, report writer, naive baseline agent (`evals/baseline_agent.py`).
- **Initial scenarios:** 10 (memory ×2, verification ×4, leakage ×1, injection ×1, scope ×1, escalation ×1).
- **Naive LLM baseline:** **N/A, no API key in this environment.** Run `ANTHROPIC_API_KEY=... python -m evals.runner --agent baseline --mode live` to fill it in.
- **Unit tests:** 53 passed.

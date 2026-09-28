# Evaluation log

One block per iteration: what changed, what ran, results, failures by category, regressions, next step.

## Iteration 0 — Baseline (2026-09-28)

- **Starter code:** the ZIP holds 6 JSON fixtures only. There is no runnable agent, so 0 scenarios can be executed against the starter.
- **Harness built:** scenario schema, independent leak detector, oracle verifier, policy-matrix oracle, runner, metrics, report writer, naive baseline agent (`evals/baseline_agent.py`).
- **Initial scenarios:** 10 (memory ×2, verification ×4, leakage ×1, injection ×1, scope ×1, escalation ×1).
- **Naive LLM baseline:** **N/A, no API key in this environment.** Run `ANTHROPIC_API_KEY=... python -m evals.runner --agent baseline --mode live` to fill it in.
- **Unit tests:** 53 passed.

## Iterations 1–2: workflow foundation + extraction/memory (Tasks 3–9)

- **Changes:** immutable state and audit, phase-gated tool registry, normalizers and the ≥3-factor verifier, rule extractor, LLM extractor with the substring-gated merge, cross-phase memory, case resolver, controller, templates, agent pipeline.
- **Tests:** 270 passed, 2 skipped (staged full-pass list).
- **Eval (rules mode, 10 scenarios):** 8/10 passed.
  - Gate compliance 17/17. Leakage 0/25. Bypass 0/10. Unauthorized tools 0/14 (1 blocked attempt). Email without consent 0/1.
  - Memory retention 2/2. Case selection 2/2. Hallucination 0/6.
- **Failures by category:**
  - *grounding:* the M1 follow-up question is not routed to `get_followup_guidance` yet (Task 10).
  - *post-process:* no send path yet (Task 15).
  - *scope:* no OOS counter or redirect yet (Task 13).
- **Safety regression found and fixed this iteration:** after verification, the claim option list showed statuses without them being in the authorized facts. The detector flagged it as a leak. Fix: the verified party's option facts now flow through the RESOLVE_INTENT allowlist, with an ownership check.
- **Next:** grounding and follow-up guidance (Task 10).

## Iteration 3: intent + grounded processing + validator (Tasks 10–12)

- **Changes:**
  - Derived facts with an injectable clock: deadline passed or remaining, payout explanation, not-in-data.
  - Follow-up guidance engine, with the document alias table and bag-of-words phrase matching.
  - Answer selection by fact id.
  - Allowlisted `ResponseContext`, the LLM responder (template draft plus citations), and the provenance validator.
  - A regenerate-once, then template, then safe-message fallback chain.
- **Tests:** 338 passed, 2 skipped. These include a leaky-responder e2e test: all 10 scenarios with a responder that always tries to leak every protected value, the forbidden "you're verified", and a false "emailed". **0 safety failures.**
- **Eval (rules):** 8/10 scenarios. Gate 17/17, leakage 0/25, bypass 0/10, unauthorized tools 0/15, email without consent 0/1.
- **Found by the validator while building this:**
  - The refusal template said "another *approved* option". "approved" is a status word, so the validator correctly rejected it before verification. Reworded, with a guard test that every pre-verification template passes the validator.
  - The email "action claim" pattern was too broad and matched "I've sent an authorization request". Narrowed.
- **Ablation note:** `--no-validator` shows the same numbers in rules mode because the templates never leak. The validator's value shows against a misbehaving LLM (the leaky-responder test). Task 16 adds that to the CLI.
- **Next:** scope, refusal recovery and escalation (Task 13).

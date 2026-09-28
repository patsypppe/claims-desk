# Production Hardening + Response Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen: native/inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement every recommendation from `docs/research/2026-09-28-production-landscape.md` and every deferred review minor. Also raise LLM-judge response quality from roughly 2.1–2.5/5 to at least 4/5, without regressing any safety metric.

**Architecture:** Keep the existing deterministic controller. Every addition is one of four kinds:
- a new *signal*: classifiers that only flag, never grant;
- a new *tool*: OTP, channel assertion, all behind the permission guard;
- a *storage* backend: SQLite behind the existing `SessionStore` / `LockoutRegistry` interfaces;
- an *eval capability*: user simulator, pass^k, traces, red team.

Response quality is improved in the responder layer only (prompt, conversation memory, dedupe state, templates). The validator is unchanged in authority.

**Tech stack additions:**
- `phonenumbers`, `email-validator`, `dateparser` (parsing)
- `presidio-analyzer`, `presidio-anonymizer`, spaCy `en_core_web_sm` (PII)
- Groq `meta-llama/llama-prompt-guard-2-86m` and `openai/gpt-oss-safeguard-20b` (signals)
- stdlib `sqlite3` and `hmac`
- promptfoo (via `npx`, dev only)
- optional `transformers` for HHEM (extra `[grounding]`, never required at runtime)

**Spec:** the research report (§4 gaps, §5 adoption) + review ledger minors + the user's request for "the quality of the responses".

## Global Constraints
- The safety metrics must stay at 0 in every mode: leakage, bypass, unauthorized tools, email without consent. The e2e suite requires all scenarios to pass.
- Classifiers (Prompt Guard, safeguard, HHEM) only **flag, redirect or escalate**. They never verify anyone, never authorize, never change phase directly.
- Tests never touch the network or the real `.env` (`CLAIMS_AGENT_SKIP_DOTENV=1`). Live calls sit behind `@pytest.mark.live` or the eval CLI.
- New features are configurable with safe defaults. The spec's "≥3 factors" behavior remains the default policy.
- Raw PII never goes to logs, audit, UI payloads, or (with redaction on) the LLM extractor.
- Coding style: immutable state, small files (<400 lines typical), TDD (RED before GREEN), conventional commits.
- Groq free tier: 8K tokens/min and 200K tokens/day on `gpt-oss-120b`. The judge and simulator default to other models (`qwen/qwen3.8-27b`, `openai/gpt-oss-20b`) so they don't consume the reply model's quota.

## Review Focus
1. **OTP brute force / oracle.** A wrong code must not reveal whether a record exists. Codes are never delivered anywhere except the on-file contact. There is an attempt cap per code, and codes expire.
2. **Redaction placeholders round-trip.** A placeholder the extractor sees must map back to the exact caller value. The model must not be able to invent placeholders to inject values (the substring gate applies to placeholders too).
3. **SQLite persistence under concurrency.** There is a per-session lock so two concurrent requests can't double-send the email or lose updates.
4. **Signed channel assertion.** Tampered, expired, or wrong-key tokens must fail closed. Assertions verify only the party they name, and only via the tool.
5. **Quality changes must not reintroduce leaks.** The responder gets more conversational context (its own previous replies) but never the caller's raw PII. The validator still gates every reply.

---

## Tasks

### Task 1: Library-backed normalizers + parsing minors
**Files:** Modify `claims_agent/normalize.py`, `extraction/lexicon.py`, `extraction/rules.py`, `pyproject.toml`. Test `tests/unit/test_normalize.py`, `tests/unit/test_rule_extractor.py`.
- Phone: `phonenumbers.parse(raw,"US")` + `is_valid_number` → E.164. Extraction via `PhoneNumberMatcher`.
- Email: `validate_email(raw, check_deliverability=False).normalized`, lowercased.
- DOB: `dateparser.parse(..., settings={"DATE_ORDER":"MDY","STRICT_PARSING":True,"REQUIRE_PARTS":["day","month","year"],"PREFER_DATES_FROM":"past"})`, falling back to the current regex. Keep the `_valid` future-date and plausibility checks.
- Minors:
  - "may" as a verb is not the month May (require a date context or a capitalized "May" followed by a day/year/"claim").
  - A bare year ("the one from 2025", "2026") becomes a year hint.
  - "ends with" is not an SSN cue unless SSN/ID/social is nearby.
- Tests: all existing normalizer tests plus `test_may_verb_not_month`, `test_bare_year_hint`, `test_phone_ends_with_not_ssn`, `test_libphonenumber_rejects_invalid_area_code`.

### Task 2: Injection & social-engineering signals (Prompt Guard 2 + gpt-oss-safeguard)
**Files:** Create `claims_agent/extraction/guard.py`. Modify `agent.py` (call the guard in llm mode), `extraction/merge.py` (OR into `injection_suspected`, add `social_engineering`), `phases/dispatch.py` (count a social-engineering flag as unsafe toward OOS/escalation, never toward verification), `config.py` (`GUARD_ENABLED`, `PROMPT_GUARD_MODEL`, `SAFEGUARD_MODEL`, `PROMPT_GUARD_THRESHOLD=0.9`).
- `PromptGuard.score(text) -> float | None`: parses the bare float string; the text is chunked to ≤512 tokens.
- `Safeguard.classify(text) -> SafeguardVerdict | None`: runs only when the regex or Prompt Guard flags, or when the text claims authority or third-party access. The 400–600 token policy covers staff impersonation, verification bypass and third-party data.
- Failure or timeout → `None` → regex-only behavior. Audit `guard_scored` with the score and category, never the text.
- Tests: stubbed Groq client covering float parsing, threshold, chunking, safeguard JSON parsing, failure → None, merge OR-ing, and "a guard flag never changes verification".

### Task 3: PII redaction before the LLM + Presidio masking/scan
**Files:** Create `claims_agent/privacy/redact.py`, `claims_agent/privacy/presidio_scan.py`. Modify `extraction/llm.py` (send redacted text), `extraction/merge.py` (map placeholders back; gate placeholders), `audit.py` (Presidio-backed free-text masking helper), `response/validator.py` (secondary Presidio PII scan: phone, email, SSN), `evals/leak_detector.py` (optional Presidio pass). Config: `REDACT_BEFORE_LLM=true`.
- Redaction: deterministic spans (DOB-like dates, 4-digit IDs after a cue, phones, emails) → `⟦DOB_1⟧`, `⟦ID4_1⟧`, `⟦PHONE_1⟧`, `⟦EMAIL_1⟧`. The extractor may return a placeholder as `raw_value`. Merge maps it back to the original span only if that placeholder was issued this turn.
- Presidio: `AnalyzerEngine` with custom recognizers for `CLAIM_ID` / `POLICY_NUMBER`, lazily initialized. If spaCy or Presidio is unavailable → skip with an audit note. It is never a hard runtime dependency.
- UI "secure field": a toggle marks the next message as sensitive. It is sent to `/api/chat` with `sensitive: true`, and the server skips the LLM extractor entirely for that turn (rules only).
- Tests: redaction round-trip; an invented placeholder is rejected; the LLM prompt contains no raw DOB/ID digits (asserted on `FakeLLM.calls`); a sensitive turn makes no LLM call; the Presidio scanner flags an unauthorized phone in a reply (skipped if the model isn't installed).

### Task 4: OTP possession factor (mock) + verification policy tiers
**Files:** Create `claims_agent/tools/otp.py` (`MockOtpService`: 6-digit codes, TTL 5 min, 3 attempts, delivered only to the on-file phone or email; mock outbox visible in the debug panel). Modify `tools/registry.py`/`impl.py` (`send_otp`, `verify_otp` tools in VERIFY_ID), `phases/verify.py`, `verification.py`, `config.py` (`VERIFICATION_POLICY = any3 | any3_or_otp | knowledge_plus_otp`, default `any3_or_otp`).
- `any3_or_otp`: ≥3 matching factors verify as before. Also, 2 matching factors plus a correct OTP to the matched record's on-file contact verifies (possession counts as the 3rd factor). The agent offers OTP when the caller refuses or can't provide a third knowledge factor.
- `knowledge_plus_otp` (step-up): ≥2 factors plus OTP is always required.
- The OTP is sent to the *candidate* record only when ≥2 factors match the same record. The reply is identical either way ("If those details match our records, we've sent a code to the contact on file"): **no oracle.**
- Tests:
  - OTP verifies with 2 factors;
  - a wrong code counts an attempt, and 3 wrong codes expire it;
  - an expired code fails;
  - the reply is identical whether or not a record matched;
  - the code is never in the reply;
  - policy tiers;
  - the permission matrix is updated (and so is `evals/policy_matrix.yaml`).

### Task 5: Pre-authenticated channel assertion
**Files:** Create `claims_agent/channel_auth.py` (HMAC-SHA256 signed `{party_id, exp, nonce}`, key `CHANNEL_SIGNING_KEY`). Modify `api.py` (`POST /api/session` accepts an optional `channel_token`), `tools` (`accept_channel_assertion` tool, VERIFY_ID only), `phases/verify.py` (a verified `method="channel"` state when the tool succeeds). A dev helper script mints demo tokens.
- Tests: valid token verifies; tampered, expired, wrong-key or replayed nonce → rejected with the generic reply; no key configured → the feature is disabled.

### Task 6: Durable SQLite sessions + lockouts, concurrency, timing
**Files:** Create `claims_agent/storage/sqlite_store.py` (`SqliteSessionStore`, `SqliteLockoutRegistry`; state serialized with `model_dump_json`). Modify `sessions.py` (interfaces), `agent.py` (per-session `threading.Lock`), `api.py` (Secure cookie flag via `COOKIE_SECURE`, pruning of the rate-limit map, a per-IP limit on session creation), `phases/verify.py` (minimum-latency padding on verification failures, `VERIFY_FAILURE_MIN_MS=400`, injectable sleeper). Config: `STORAGE=memory|sqlite`, `SQLITE_PATH`.
- Tests: state survives a new store instance; lockout persists across instances; two concurrent handles on one session send the email only once; expired sessions are pruned; the session-creation rate limit applies; failure latency is padded (fake sleeper records the pad).

### Task 7: Warm handoff + verification documentation
**Files:** Modify `tools/impl.py` (`escalate_to_human` payload), `audit.py` (`verification_record` event), `phases/verify.py` / `representative.py`.
- The handoff includes:
  - a masked case summary (reusing `grounding/summary.py`),
  - the verification method (`self` / `representative` / `otp` / `channel`),
  - the masked factors used,
  - the representative's name, relationship and consent status,
  - the recent turn topics,
  - the reason.
- A `verification_record` audit event is written on success (HIPAA §164.514(h) documentation).
- Tests: the payload has no raw PII; it includes method and factor list; the representative authority is recorded.

### Task 8: Repair patterns
**Files:** Modify `extraction/lexicon.py` (REPEAT, START_OVER, SKIP cues), `extraction/schema.py` (`requested_action` gains `repeat`, `start_over`, `skip`), `phases/dispatch.py`, `response/templates.py`, `state.py` (`last_reply` so "repeat" re-sends it).
- `repeat` → re-send the last reply (validated again).
- `start_over` → keep verification, clear intent, case and candidates → RESOLVE_INTENT. Before verification, clear captured factors except refusals and counters.
- `skip` in VERIFY_ID → treated as a refusal of the expected field.
- Tests plus 3 scenarios (`r_repeat`, `r_start_over`, `r_skip_question`).

### Task 9: Promissory-language guard + validator false positives + optional HHEM
**Files:** Modify `response/validator.py`. Create `evals/hhem.py` (optional, lazy `transformers`, not in the runtime path).
- A deny-list of promises and speculation about outcomes: "will be approved/paid/overturned", "guarantee", "should be approved", "probably be approved", "definitely", "I promise". Speculation is allowed only as a quoted guideline fact.
- Review minors on false positives:
  - "nothing will be paid" is not the status `paid`;
  - "original pathology report" is allowed when the guideline fact is present;
  - a month-day date (e.g. "March 1") matches any fact date with that month and day.
- HHEM: `grounding_score(premise_facts, reply) -> float | None`, reported as an eval metric only when installed.
- Tests: promissory phrases are rejected; the false-positive cases pass; the HHEM wrapper returns None when not installed.

### Task 10: Response quality (the main quality lever)
**Files:** Modify `response/llm_responder.py` (style guide; its own last 3 replies passed as `previous_agent_replies`; "don't repeat an apology or offer already made"; one empathy clause max, only for detected emotion; answer first, then one question; ≤3 sentences unless listing), `state.py` (`offers_made: frozenset[str]`, `empathy_turns`), `controller.py` / `policy/emotion.py` (suppress repeated empathy and repeated representative offers; escalate offers only once per reason), `response/templates.py` (shorter, less robotic templates: remove duplicate docs sentence, fold the deadline caveat into one clause, don't use the first name on every turn), `response/context.py` (adds `previous_agent_replies`, which contain only replies that already passed validation).

Deterministic quality metrics in `evals/quality.py`:
- words per reply (target median ≤ 45),
- repetition rate: 4-gram overlap with the agent's previous replies (target < 15%),
- repeated offers per conversation (target 0),
- questions per reply (target ≤ 1),
- empathy-phrase frequency when emotion is neutral (target 0).

Judge: configurable `JUDGE_MODEL` (default `qwen/qwen3.8-27b`), with a calibrated rubric including 2 anchored examples per dimension.
- Targets: judge ≥ 4.0 on each dimension; safety unchanged.
- Tests: the deterministic metrics compute correctly; the responder payload contains previous replies and no raw PII; an offer made once isn't repeated (template + state); emotion empathy isn't repeated on consecutive turns.

### Task 11: Eval upgrades (traces, end-state, pass^k, transcript export)
**Files:** Modify `evals/scenario.py` (`expected_tool_trace: list[str]` as an ordered subsequence; `end_state: {ticket: bool, emails_sent: int, consent: …}`), `evals/runner.py`, `evals/metrics.py` (pass^k over k repeats per scenario on the hard-safety invariants and on task completion), `evals/cli.py` (`--repeats k` groups results by scenario for pass^k). Create `evals/export.py` (audit trace → YAML scenario skeleton with the observed state as expectations; masked caller text needs manual review).
- Tests: trace subsequence matching; end-state checks; pass^k math; the exporter round-trips into a loadable Scenario.

### Task 12: LLM caller simulator (τ-bench style)
**Files:** Create `evals/simulator.py` (a `SimulatedCaller` driven by a persona card: goal, known facts, disallowed info, style, stop condition, adversarial tactics; LLM via the provider-agnostic `LLMClient`), `evals/personas/*.yaml` (8 personas: cooperative Margaret, anxious deadline, angry denial, confused elderly, social-engineer who knows 2 factors, fake "previous agent verified me", representative David, off-topic chatter), `evals/sim_runner.py` (runs N conversations per persona, applies the global invariants from `runner.py`, reports pass^k and the judge).
- Tests: a scripted FakeLLM persona drives a full conversation deterministically; the invariants are applied; the stop conditions (goal met, max turns, escalated) work.

### Task 13: promptfoo red team against the live API
**Files:** Create `evals/redteam/promptfooconfig.yaml` and `evals/redteam/README.md`. Modify `api.py` (`X-Session-Id` header accepted only when `ALLOW_HEADER_SESSIONS=true`; still server-issued ids only).
- Plugins: `pii:direct`, `pii:session`, `pii:social`, `bola`, `rbac`, `prompt-extraction`, `hijacking`, plus a custom policy. Strategies are the documented ones. The provider for attack generation is set explicitly.
- Tests: header sessions are disabled by default; when enabled they still reject unknown ids.
- Run: `npx promptfoo redteam run` if Node is available, and record the results.

### Task 14: Docs, live re-run, final review
- Update the README (verification policies, OTP, channel auth, storage, guard, redaction, repair patterns, quality metrics, simulator, red team), `.env.example`, `docs/eval-log.md` and the research doc status.
- Live Groq re-run (quota permitting): final agent + judge + the simulator subset. Record baseline-vs-final and the before/after quality numbers.
- Fresh-context final review; fix Critical/Important with RED→GREEN; commit and push to `main`.

## Status table

| Task | Rec source | Status |
|---|---|---|
| 1 Library normalizers + parsing minors | OSS #2, review minors 11/12/18 | NEXT |
| 2 Prompt Guard + safeguard | OSS #1, #4, gap 12 | NEXT |
| 3 Redaction + Presidio + secure field | gap 4, OSS #3 | NEXT |
| 4 OTP + policy tiers | gap 1 | NEXT |
| 5 Channel assertion | gap 7 | NEXT |
| 6 SQLite + concurrency + timing + cookie | gap 2, 10, minors 15/16 | NEXT |
| 7 Warm handoff + verification record | gap 10, 11 | NEXT |
| 8 Repair patterns | gap 8 | NEXT |
| 9 Promissory guard + FP fixes + HHEM | gap 5, minor 17 | NEXT |
| 10 Response quality | user request, live judge 2.1–2.5 | NEXT |
| 11 Traces/end-state/pass^k/export | gap 6, 3, 9 | NEXT |
| 12 LLM caller simulator | gap 3 | NEXT |
| 13 promptfoo red team | OSS #5 | NEXT |
| 14 Docs + live + review | — | NEXT |

**Also resolved as part of the tasks above:**
- Minor 13 (reference wording): already fixed.
- Minor 14 (policy typo counts as an attempt): Task 1 changes this. A policy contradiction now returns the generic re-confirm without consuming an attempt when the PII factors all match; a PII mismatch still counts.
- Minor 19 (debug panel default): Task 6 sets `DEBUG_PANEL` to default true only when `AGENT_MODE=rules` or `APP_ENV=dev`, and never includes validator violation categories in API responses.

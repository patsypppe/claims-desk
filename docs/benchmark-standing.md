# Where Claims Desk stands against published baselines (2026-09-28)

This page compares our measured numbers with published numbers from benchmarks, standards bodies and vendors, and says what each comparison is worth.

- Our numbers come from three sources:
  - the deterministic eval suite (rules mode);
  - a live-LLM eval subset;
  - a 36-turn adversarial live probe at one prompt per 15 s.
- All live runs used Groq: `qwen/qwen3.8-27b` for the probe, and `openai/gpt-oss-120b` replies with `gpt-oss-20b` extraction and judge for the eval.
- Rows marked **vendor** are self-reported and unaudited.
- Most public benchmarks measure a *model*. We measure a *system* (an SOP controller around a model), so absolute numbers are rarely apples-to-apples. The verdict column says how comparable each row is.

## Scorecard

| Dimension | Published baseline | Claims Desk (measured) | Verdict |
|---|---|---|---|
| **Direct prompt-injection / jailbreak success** | CyberSecEval 2: 26–41% injection success on GPT-4, Llama-3-70B and others [1]. InjecAgent: 24% (GPT-4, base), 47% (enhanced), >80% (Llama2-70B) [2]. | **0 successful attacks** on 36 live probe turns: encoded, multilingual, role-play, fake-system-JSON, prompt extraction, social engineering, enumeration, BOLA and consent tricks. **0/94** leak turns and **0/33** bypasses on the red-team scenarios. A naive single-prompt agent on the *same model* leaked on **8/45** turns (17.8%) and was bypassed **2/15** times (13.3%). | **Ahead**, and it's structural. Disclosure is decided by code, not by the model. The same-model naive baseline shows the gap is the architecture. |
| **Defence depth (ablation)** | AgentDojo: 54.5% undefended ASR, down to 0% with a PromptArmor-style detector [3]. | Leaky-responder ablation, where the model tries to leak every turn: **93/94** leaks with the validator removed, **0/94** with it. | **At the defended frontier** for *direct* injection. We have not tested indirect injection through tool outputs, which is what AgentDojo measures. Our tool data is fixture data, not attacker-controlled. |
| **Task completion** | τ-bench pass^1: retail 60–86% and airline 42–70% across GPT-4o to Claude Sonnet 4.5. τ²-bench top systems score 85–88% [4][5]. GPT-4o drops from ~60% (k=1) to ~25% (k=8) on retail pass^k [5]. | Deterministic: **37/37** scenarios, run-to-run identical, so pass^k = pass^1 by construction. Live subset: see *Live eval* below. | **Not comparable in absolute terms.** Our scenarios are single-domain and scripted, and τ-bench uses an LLM user simulator over large policy documents. The *pass^k* property is where we're strong: the controller makes the SOP path deterministic, so the k-trial decay τ-bench documents doesn't apply to the safety path. |
| **Hallucination / grounding** | Vectara HHEM leaderboard: best model 3.3%, **gpt-oss-120b >10%** on summarization [6]. RAGAS faithfulness in published RAG systems: 0.64–0.90 [7]. | Hallucination rate **0/32** checked factual atoms in the last full live run. Every ID, amount, date, status and document in a reply must trace to an allowlisted fact, or the validator regenerates, templates, or falls back. | **Ahead on checkable atoms**, using the same gpt-oss-120b that scores >10% raw on HHEM. Caveat: we check atoms (IDs, amounts, dates), not free-text paraphrase faithfulness. HHEM scoring is available offline (`evals/hhem.py`) but wasn't part of this run. |
| **Identity verification strength** | NIST SP 800-63B-4 (July 2025) **does not accept KBA** as an authenticator [8]. Pindrop (**vendor**): fraudsters passed KBA **92%** of the time, genuine callers only 46% [9]. | Default policy: any 3 of name, DOB, phone, email and ID-last-4, which is knowledge-based. An OTP possession factor exists (`v10_otp_possession`, the probe's C13) and is offered when factors are refused. | **Behind current guidance by default.** It is fine for a demo, but set `VERIFICATION_POLICY` to require OTP for disclosure in production. The code path exists and is tested. |
| **Social-engineering resistance** | Help desks are targeted in 42% of vishing, and simulated vishing succeeds on ~6.5% of employees [10]. | 0/3 on the probe's C03 (husband pretext, "fine, I'm Margaret then", fake prior-verification ticket). Curly-apostrophe third-party bypass found by review and **fixed** this pass. | **Ahead of human baselines on the scripted pretexts.** Residual risk is someone who simply knows 3 semi-public facts. That's the KBA row, and OTP is the fix. |
| **Crisis handling** | Contact-center practice: stop the process, respond with care, give 988, hand off to a human. | 988 plus a warm handoff with a ticket, in any phase. This pass removed a live bug where the reply also said "keep this conversation respectful" to a suicidal caller. | **Meets practice** after the fix. |
| **Escalation rate** | Industry average 10–15% of contacts, 25–30% for weak operations [11]. | Not measurable without real traffic mix. The scenario set is deliberately adversarial. | N/A. It needs production traffic. |
| **Resolution / containment** | Intercom Fin **67–76% (vendor)**, 45–53% independently measured; Deloitte AI voice containment 41% average (29% healthcare) [11][12]. | Not measurable without real traffic. | N/A |
| **Conversation quality (LLM judge)** | GPT-4-as-judge agrees with humans 85% of the time on MT-Bench (human-human agreement is 81%) [13]. | See *Live eval*: empathy, clarification and naturalness on a 1–5 scale, judged by a *different* model from the one replying. There is no human calibration yet. | **Advisory only.** Without human-labelled calibration the absolute scores are directional. |
| **Latency** | Chat support expectation is a few seconds per reply. | Probe p50 **~17 s/turn**, dominated by the free-tier 8K tokens/min throttle. Unthrottled turns ran 1.5–3 s. | **Behind, because of the environment.** A paid tier removes the throttle. |

## What this iteration changed (all test-first; the suite and the deterministic 37/37 eval stay green)

- **Critical (review):**
  - Curly apostrophes (`I’m Margaret Chen’s husband`) bypassed every third-party pattern and verified a third party. Input is now normalized.
- **Live LLM, qwen:**
  - The LLM `claim_id` gate let `None == None` through.
  - An LLM-only `third_party` label locked out a policyholder correcting their name.
  - The DOB's birth month and year leaked into claim-date hints, causing "I don't see that specific claim".
  - An LLM-invented `status` silently picked a claim.
  - "my mother" was read as the caller's relation, which refused a listed rep.
  - A spelled name ("Margaret, M-A-R-G-A-R-E-T") overwrote the surname.
  - A hedged "hmm ok maybe" closed the email offer.
  - Crisis and threat collided, producing boundary language.
- **Review, Important:**
  - The crisis lexicon fired on injury talk ("I hurt myself in the accident"), and the threat lexicon on "I'll get you the report".
  - Read-back refusal swallowed ordinary questions and human requests.
  - Letter runs ("C-L-M 2048") were taken as names.
  - "That's Ridiculous" overwrote the first name.
  - "No, not that one please" selected the claim.
- **Helpfulness:**
  - Provider and insurer possessives are no longer treated as other-person PII.
  - Only question sentences add asked attributes.
  - Representatives hear "the policyholder's account".

## Honest gaps

1. **Default verification is knowledge-based.** NIST 800-63B-4 doesn't accept this, so require OTP in production.
2. **No live pass^k.** The Groq free tier (200K tokens/day per model) can't fund a k≥3 simulator run. `python -m evals.sim_runner --runs 3` is ready for a paid key.
3. **No indirect-injection tests** (AgentDojo-style), because tool outputs are trusted fixtures. Documents or uploads would need this.
4. **The judge isn't human-calibrated.** A 30–50-conversation human-labelled set would make the quality numbers comparable to MT-Bench-style agreement.
5. **Single-language replies.** A Spanish injection is handled safely, but the answer is in English.

## Sources

1. CyberSecEval 2, Meta, 2024 — https://arxiv.org/pdf/2404.13161
2. InjecAgent, ACL Findings 2024 — https://aclanthology.org/2024.findings-acl.624/
3. PromptArmor on AgentDojo, 2025 — https://arxiv.org/pdf/2507.15219
4. τ-bench leaderboards — https://llm-stats.com/benchmarks/tau-bench-retail , https://llm-stats.com/benchmarks/tau-bench-airline
5. τ-bench retail/airline pass^k — https://benchmarkingagents.com/tau-bench-retail-airline/ ; τ²-bench — https://sophon.at/evals/tau2-bench
6. Vectara hallucination leaderboard — https://github.com/vectara/hallucination-leaderboard
7. RAGentA, 2025 — https://arxiv.org/pdf/2506.16988 ; biomedical RAG benchmarking, 2026 — https://arxiv.org/pdf/2605.02520
8. NIST SP 800-63B-4 — https://csrc.nist.gov/pubs/sp/800/63/b/4/final
9. Pindrop report (vendor), 2022 — https://www.businesswire.com/news/home/20220420005041/en/
10. Social-engineering statistics — https://deepstrike.io/blog/social-engineering-statistics-2025 , https://app.stationx.net/articles/social-engineering-statistics
11. Contact-center KPI roundups (SQM, Deloitte Digital), 2025–26, via eesel/Lorikeet/StealthAgents summaries
12. Intercom Fin (vendor) — https://www.createwith.com/tool/intercom/updates/intercom-ships-200-updates-in-2025-fin-3-reaches-67-average-resolution-rate ; independent — https://clonedesk.ai/blog/intercom-fin-limitations
13. Zheng et al., *Judging LLM-as-a-Judge with MT-Bench*, 2023 — https://arxiv.org/pdf/2306.05685

## Live evidence from this pass

**Adversarial probe (live LLM, one prompt every 15 s, `qwen/qwen3.8-27b`, 0 degraded turns).**

- 14 conversations, 36 turns covering:
  - the spec sample;
  - ASR typos with a spelled-name correction;
  - social engineering;
  - five injection styles: base64, Spanish, role-play, prompt extraction, fake system JSON;
  - post-verification enumeration and BOLA;
  - crisis, a threat, and over-disclosure requests;
  - consent tricks (a redirect to another address, a hedge);
  - a 300-word rambling input, a three-part question, fullwidth and emoji unicode;
  - OTP step-up and a listed representative.
- First pass on this iteration's starting code: 23 of 30 turns clean. It surfaced 8 real defects, all fixed test-first.
- Final: **36/36 turns pass on the fixed code** (C02 and C09 re-probed after their fixes).
- **0 leaks, 0 bypasses, 0 read-backs** throughout.

**Stratified live eval (15 scenarios, every category).**

- Hard safety held: gate 20/20, leakage 0/50, bypass 0/15, unauthorized tools 0/56, email without consent 0/3. Task completion was 15/15.
- **Caveat:** 94% of turns ran degraded. An earlier run lost its report to a path-length bug (now fixed) after spending the day's gpt-oss quota. So this run mostly measured the deterministic fallback, and the judge could not score. The honest reading is that **when the LLM provider fails, the agent fails safe and still completes the SOP.** Quality-judge numbers need a re-run on a fresh quota or a paid key: `python -m evals.runner --mode live --judge --repeats 3`.
- The last non-degraded judged run, earlier today on gpt-oss-120b, scored empathy 3.38, clarification 3.94 and naturalness 3.79 out of 5 (34 conversations, advisory).

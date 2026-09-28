# Red team with promptfoo

The config drives multi-turn attacks against the running API. Sessions are server-issued; for tooling only,
`ALLOW_HEADER_SESSIONS=true` exposes the new session id in the `/api/session` response body and accepts it back in
an `X-Session-Id` header (unknown ids are still rejected). Never enable it in production.

Attack generation uses Groq through its OpenAI-compatible endpoint (`GROQ_API_KEY`), so nothing goes to OpenAI.
Groq's free tier (8K tokens/min, 200K tokens/day on gpt-oss-120b) limits run size; keep `numTests` small.

Results: `npx promptfoo@latest view` opens the report. Treat any `pii:*`, `bola`, `rbac` or `policy` failure as a
safety bug. Reproduce it as a YAML scenario in `evals/scenarios/` (see `evals/export.py`) before fixing it.

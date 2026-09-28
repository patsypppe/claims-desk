"use strict";
// Claims Desk demo client. All rendering uses textContent (no innerHTML) — agent output is untrusted text.
const PHASES = ["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS", "COMPLETE"];
const FIELD_NAMES = { name: "name", dob: "dob", phone: "phone", email: "email", id_last4: "id last 4" };
const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function addMessage(who, text, kind) {
  const item = el("li", `msg ${kind}`);
  item.append(el("span", "msg-who", who), el("div", "msg-body", text));
  $("transcript").append(item);
  item.scrollIntoView({ block: "end", behavior: "smooth" });
  return item;
}

function fillKv(target, rows, emptyText) {
  const dl = $(target);
  dl.replaceChildren();
  const entries = rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!entries.length) { dl.append(el("dd", "empty", emptyText)); return; }
  for (const [k, v] of entries) dl.append(el("dt", "", k), el("dd", "", String(v)));
}

function renderPhase(snapshot) {
  const idx = PHASES.indexOf(snapshot.phase);
  document.querySelectorAll("#phase-rail li").forEach((li, i) => {
    li.classList.toggle("done", idx > i || snapshot.phase === "COMPLETE");
    li.classList.toggle("current", li.dataset.phase === snapshot.phase);
  });
  const banner = $("escalation-banner");
  banner.hidden = !snapshot.escalated;
  banner.textContent = snapshot.escalated
    ? `ESCALATED · reason: ${snapshot.escalation_reason} · ticket ${snapshot.escalation_ticket}` : "";
}

function renderVerification(snapshot) {
  const count = Math.min(snapshot.captured_count, 3);
  const meter = document.querySelector(".meter");
  $("meter-fill").style.transform = `scaleX(${snapshot.verified ? 1 : count / 3})`;
  meter.classList.toggle("verified", snapshot.verified);
  $("verify-status").textContent = snapshot.verified
    ? `Verified ✓ (${snapshot.verification_method}) — set by verify_identity result`
    : `${snapshot.captured_count} captured · ${snapshot.counters.failed_verifications} failed attempt(s) · not verified`;
  const rows = Object.entries(snapshot.captured_fields).map(([k, v]) => [FIELD_NAMES[k] || k, v]);
  if (snapshot.refused_fields.length) rows.push(["refused", snapshot.refused_fields.join(", ")]);
  if (snapshot.expected_field) rows.push(["asking for", FIELD_NAMES[snapshot.expected_field]]);
  fillKv("captured-fields", rows, "nothing captured yet");
}

function renderState(snapshot) {
  renderPhase(snapshot);
  renderVerification(snapshot);
  fillKv("intent-hints", Object.entries(snapshot.intent_hints), "no hints yet");
  fillKv("case-consent", [
    ["case", snapshot.selected_case_id],
    ["candidates", snapshot.candidate_case_ids.join(", ")],
    ["email", snapshot.consent],
    ["llm", snapshot.degraded ? "degraded → rules" : null],
  ], "no case selected");
  const c = snapshot.counters;
  fillKv("counters", [["off-topic", c.out_of_scope], ["refusals", c.refusals],
    ["clarifications", c.clarifications], ["heated turns", c.heated_turns]], "—");
}

function describe(event) {
  const d = event.detail;
  switch (event.kind) {
    case "tool_called": return [`✓ ${d.tool} @ ${d.phase}`, "ok"];
    case "tool_blocked": return [`✕ ${d.tool} blocked (${d.reason})`, "blocked"];
    case "tool_failed": return [`! ${d.tool} failed (${d.reason})`, "warn"];
    case "transition": return [`→ ${d.from} ⇒ ${d.to} (${d.cause})`, "transition"];
    case "validator_reject": return [`✕ reply rejected: ${d.violations.slice(0, 3).join(", ")}`, "blocked"];
    case "fallback_used": return [`↺ template fallback (${d.reason})`, "warn"];
    case "llm_value_rejected": return [`✕ LLM value not in caller text (${d.field})`, "blocked"];
    case "injection_flagged": return ["⚑ injection attempt flagged — state unchanged", "blocked"];
    case "escalated": return [`⇪ escalated: ${d.reason}`, "warn"];
    case "consent": return [`✎ email consent: ${d.outcome}`, "transition"];
    case "llm_degraded": return ["! LLM unavailable — rules fallback", "warn"];
    default: return [null, ""];
  }
}

function renderEvents(events, turn) {
  const log = $("event-log");
  for (const event of events) {
    const [text, cls] = describe(event);
    if (!text) continue;
    log.prepend(el("li", cls, `t${turn} ${text}`));
  }
}

let turn = 0;
async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail?.[0]?.msg || data.detail || `Request failed (${response.status})`);
  return data;
}

async function startSession(path = "/api/session") {
  const info = await post(path);
  turn = 0;
  $("transcript").replaceChildren();
  $("event-log").replaceChildren();
  if (info.mode) $("mode-badge").textContent = `mode: ${info.mode}`;
  addMessage("Agent", "Hello, you've reached Claims Support. How can I help you today?", "agent");
  renderState({ phase: "VERIFY_ID", verified: false, captured_fields: {}, captured_count: 0, refused_fields: [],
    intent_hints: {}, selected_case_id: null, candidate_case_ids: [], counters: { failed_verifications: 0,
    out_of_scope: 0, refusals: 0, clarifications: 0, heated_turns: 0 }, consent: "NOT_OFFERED", escalated: false,
    expected_field: null, degraded: false });
}

async function send(text, sensitive) {
  addMessage("You", sensitive ? "•••• (secure entry)" : text, "caller");
  const pending = addMessage("Agent", "…", "agent typing");
  $("send-btn").disabled = true;
  try {
    const data = await post("/api/chat", { text, sensitive });
    turn += 1;
    pending.remove();
    addMessage("Agent", data.reply, "agent");
    if (data.snapshot) renderState(data.snapshot);
    if (data.events) renderEvents(data.events, turn);
  } catch (error) {
    pending.remove();
    addMessage("System", error.message, "system");
  } finally {
    $("send-btn").disabled = false;
    $("message").focus();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = $("composer");
  const input = $("message");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    const secure = $("secure-toggle");
    send(text, secure.checked);
    secure.checked = false;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });
  $("reset-btn").addEventListener("click", () => startSession("/api/reset").catch((e) => addMessage("System", e.message, "system")));
  startSession().catch((e) => addMessage("System", e.message, "system"));
});

// Thin client. Renders exactly what the API returns: no metric arithmetic, no rounding.
// Number formatting only adds thousands separators (Intl.NumberFormat) and the unit label.
// All text goes in via textContent; nothing from the API is parsed as HTML.
"use strict";

const TOKEN_KEY = "nb_token";
const PAGE_SIZE = 25;
const STANDARD_KEYS = new Set(["metric", "label", "unit", "value", "breakdown", "params"]);

const $ = (id) => document.getElementById(id);
const state = { page: 1, stage: "" };

// ---------- api ----------

class AuthError extends Error {}

async function api(path, options = {}) {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) throw new AuthError("signed out");
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* not json */ }
    throw new Error(detail);
  }
  return resp.json();
}

function handleError(err, show) {
  if (err instanceof AuthError) { signOut(); return; }
  show(err.message);
}

// ---------- formatting (presentation only) ----------

const numberFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 20 });
const signedFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 20, signDisplay: "exceptZero" });

function formatNumber(v, signed = false) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  return (signed ? signedFmt : numberFmt).format(v);
}

const UNIT_SUFFIX = { days: " days", percent: "%", count: "", INR: "" };

function valueWithUnit(v, unit, signed = false) {
  if (v === null || v === undefined) return "—";
  const n = formatNumber(v, signed);
  if (unit === "INR") return `₹${n}`;
  return n + (UNIT_SUFFIX[unit] ?? (unit ? ` ${unit}` : ""));
}

function humanise(key) {
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function el(tag, opts = {}, ...children) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined) node.textContent = opts.text;
  for (const c of children) if (c) node.append(c);
  return node;
}

// ---------- metrics ----------

function renderBreakdown(rows) {
  const cols = Object.keys(rows[0]);
  const isNum = cols.map((c) => rows.some((r) => typeof r[c] === "number"));
  const head = el("tr", {}, ...cols.map((c, i) => el("th", { className: isNum[i] ? "num" : "", text: humanise(c) })));
  const body = rows.map((r) =>
    el("tr", {}, ...cols.map((c, i) => el("td", { className: isNum[i] ? "num" : "", text: formatNumber(r[c]) }))));
  return el("table", {}, el("thead", {}, head), el("tbody", {}, ...body));
}

function renderMetric(card, m) {
  card.className = "metric";
  card.replaceChildren();
  card.append(el("span", { className: "label", text: m.label }));

  const value = el("span", { className: "value num" });
  if (m.unit === "INR") value.textContent = valueWithUnit(m.value, m.unit);
  else {
    value.textContent = formatNumber(m.value);
    if (m.value !== null && m.value !== undefined && m.unit && m.unit !== "count") {
      value.append(el("span", { className: "unit", text: m.unit === "percent" ? "%" : m.unit }));
    }
  }
  card.append(value);

  // Extra fields the metric returns (e.g. previous / change / change_percent), shown as delivered.
  const extras = Object.keys(m).filter((k) => !STANDARD_KEYS.has(k));
  if (extras.length) {
    const parts = extras.map((k) => {
      const unit = k.endsWith("_percent") ? "percent" : m.unit;
      const signed = k.startsWith("change");
      return `${humanise(k)} ${valueWithUnit(m[k], unit, signed)}`;
    });
    card.append(el("span", { className: "delta num", text: parts.join(" · ") }));
  }

  const params = Object.entries(m.params || {}).filter(([, v]) => v !== null && v !== "None");
  if (params.length) {
    card.append(el("span", { className: "params", text: params.map(([k, v]) => `${humanise(k)} ${v}`).join(" · ") }));
  }

  if (Array.isArray(m.breakdown) && m.breakdown.length) {
    const details = el("details", {}, el("summary", { text: "Breakdown" }));
    details.append(renderBreakdown(m.breakdown));
    card.append(details);
  }
}

function renderMetricError(card, def, message) {
  card.className = "metric";
  card.replaceChildren(
    el("span", { className: "label", text: def.label }),
    el("p", { className: "error", text: `Couldn't load: ${message}` }),
  );
  const retry = el("button", { className: "link", text: "Retry" });
  retry.type = "button";
  retry.addEventListener("click", () => loadMetric(card, def));
  card.append(retry);
}

async function loadMetric(card, def) {
  card.className = "metric loading";
  card.replaceChildren(el("span", { className: "label", text: def.label }), el("span", { className: "value", text: "0" }));
  try {
    renderMetric(card, await api(`/metrics/${encodeURIComponent(def.name)}`));
  } catch (err) {
    handleError(err, (msg) => renderMetricError(card, def, msg));
  }
}

async function loadMetrics() {
  const grid = $("metrics");
  grid.replaceChildren();
  let defs;
  try {
    defs = await api("/metrics");
  } catch (err) {
    handleError(err, (msg) => grid.append(el("p", { className: "error", text: `Couldn't load metrics: ${msg}` })));
    return;
  }
  for (const def of defs) {
    const card = el("article", { className: "metric" });
    card.title = def.description || "";
    grid.append(card);
    loadMetric(card, def);
  }
}

// ---------- applications ----------

function stageCell(a) {
  const td = el("td", {}, el("span", { className: "tag", text: a.current_stage || "—" }));
  if (a.is_orphan) td.append(" ", el("span", { className: "tag orphan", text: "Unknown req" }));
  return td;
}

function appRow(a) {
  const [date, time] = String(a.applied_at || "").split("T");
  return el("tr", {},
    el("td", { className: "id", text: a.application_id }),
    el("td", {}, document.createTextNode(a.candidate_name || "—"), el("span", { className: "sub", text: a.candidate_source || "" })),
    el("td", {}, document.createTextNode(a.candidate_email || "—"), el("span", { className: "sub", text: a.candidate_phone || "" })),
    el("td", {}, document.createTextNode(a.req_id || "—"), el("span", { className: "sub", text: a.req_title || "" })),
    stageCell(a),
    el("td", { className: "num" }, document.createTextNode(date || "—"), el("span", { className: "sub", text: (time || "").slice(0, 5) })),
  );
}

async function loadApplications() {
  const params = new URLSearchParams({ page: String(state.page), page_size: String(PAGE_SIZE) });
  if (state.stage) params.set("stage", state.stage);
  $("apps-error").hidden = true;
  try {
    const data = await api(`/applications?${params}`);
    $("apps-body").replaceChildren(...data.items.map(appRow));
    $("apps-empty").hidden = data.items.length > 0;
    const first = data.total ? (data.page - 1) * data.page_size + 1 : 0;
    const last = first ? first + data.items.length - 1 : 0;
    $("apps-range").textContent = `${formatNumber(first)}–${formatNumber(last)} of ${formatNumber(data.total)}`;
    $("prev").disabled = data.page <= 1;
    $("next").disabled = last >= data.total;
  } catch (err) {
    handleError(err, (msg) => {
      $("apps-error").textContent = `Couldn't load applications: ${msg}`;
      $("apps-error").hidden = false;
    });
  }
}

// ---------- session ----------

const ROLE_LABEL = { admin: "Admin", hiring_manager: "Hiring manager", recruiter: "Recruiter" };

async function showApp() {
  let me;
  try {
    me = await api("/me");
  } catch (err) {
    signOut();
    return;
  }
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("me-name").textContent = me.name;
  $("me-role").textContent = ROLE_LABEL[me.role] || me.role;
  $("scope-line").textContent = me.role === "admin"
    ? `All ${formatNumber(me.visible_requisitions)} requisitions, including applications with no matching requisition.`
    : `The ${formatNumber(me.visible_requisitions)} requisitions where you are the ${ROLE_LABEL[me.role].toLowerCase()}.`;
  state.page = 1;
  loadMetrics();
  loadApplications();
}

function signOut() {
  sessionStorage.removeItem(TOKEN_KEY);
  // Reset view state so the next user doesn't inherit the previous user's filter or page.
  state.page = 1;
  state.stage = "";
  $("stage").value = "";
  $("apps-range").textContent = "";
  $("app-view").hidden = true;
  $("login-view").hidden = false;
  $("metrics").replaceChildren();
  $("apps-body").replaceChildren();
}

async function onLogin(e) {
  e.preventDefault();
  const form = e.target;
  const err = $("login-error");
  err.hidden = true;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const resp = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: form.email.value, password: form.password.value }),
    });
    if (!resp.ok) throw new Error(resp.status === 401 ? "Email or password is incorrect." : `Sign-in failed (HTTP ${resp.status}).`);
    sessionStorage.setItem(TOKEN_KEY, (await resp.json()).access_token);
    form.password.value = "";
    await showApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("login-form").addEventListener("submit", onLogin);
  for (const b of document.querySelectorAll("[data-email]")) {
    b.addEventListener("click", () => {
      $("login-form").email.value = b.dataset.email;
      $("login-form").password.focus();
    });
  }
  $("logout").addEventListener("click", signOut);
  $("stage").addEventListener("change", (e) => { state.stage = e.target.value; state.page = 1; loadApplications(); });
  $("prev").addEventListener("click", () => { state.page -= 1; loadApplications(); });
  $("next").addEventListener("click", () => { state.page += 1; loadApplications(); });

  if (sessionStorage.getItem(TOKEN_KEY)) showApp();
  else $("login-view").hidden = false;
});

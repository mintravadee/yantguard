"use strict";
// Yant Guard dashboard. All text from the server goes in through textContent, never innerHTML.
const PALETTE = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

function el(tag, attrs, text) {
  const e = document.createElement(tag);
  for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}
function svg(tag, attrs, text) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}
const money = (x) => x == null ? "-" : "$" + (Math.abs(x) < 1 ? x.toFixed(4) : x.toFixed(2));
const int = (x) => x == null ? "-" : Number(x).toLocaleString();
const when = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString(); };
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---- tooltip
const tip = $("tip");
function showTip(evt, text) {
  tip.textContent = text; tip.hidden = false;
  tip.style.left = Math.min(evt.clientX + 14, window.innerWidth - 270) + "px";
  tip.style.top = (evt.clientY + 14) + "px";
}
const hideTip = () => { tip.hidden = true; };

// ---- tables
function table(container, columns, rows, empty) {
  container.replaceChildren();
  if (!rows.length) { container.appendChild(el("p", { class: "muted" }, empty || "Nothing to show yet.")); return; }
  const t = el("table"), head = el("tr");
  columns.forEach((c) => head.appendChild(el("th", c.num ? { class: "num" } : {}, c.label)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  rows.forEach((r) => {
    const tr = el("tr");
    columns.forEach((c) => {
      const v = c.fmt ? c.fmt(r[c.key], r) : (r[c.key] == null ? "-" : String(r[c.key]));
      tr.appendChild(el("td", c.num ? { class: "num" } : {}, v));
    });
    body.appendChild(tr);
  });
  t.appendChild(body); container.appendChild(t);
}

// ---- headline numbers
function kpiTile(label, value) {
  const d = el("div", { class: "kpi" });
  d.appendChild(el("div", { class: "label" }, label));
  d.appendChild(el("div", { class: "value" }, value));
  return d;
}
function renderKpis(k) {
  $("kpis").replaceChildren(
    kpiTile("Requests", int(k.requests)),
    kpiTile("Success rate", k.success_rate == null ? "-" : Math.round(k.success_rate) + "%"),
    kpiTile("Equivalent cost", money(k.cost_usd)),
    kpiTile("Tokens", int(k.tokens)),
    kpiTile("Avg latency", k.avg_latency_ms == null ? "-" : Math.round(k.avg_latency_ms) + " ms"));
  $("sec-kpis").replaceChildren(kpiTile("Values masked", int(k.filter_masked)), kpiTile("Values blocked", int(k.filter_blocked)));
}

// ---- budgets (status is always written out, never colour alone)
const BADGE = { ok: "✅ OK", warning: "⚠️ WARNING: over 80%", exceeded: "⛔ BLOCKED: budget used up" };
function renderBudgets(list) {
  const box = $("budgets"); box.replaceChildren();
  if (!list.length) { box.appendChild(el("p", { class: "muted" }, "No departments yet.")); return; }
  list.forEach((b) => {
    const row = el("div", { class: "budget" });
    row.appendChild(el("div", { class: "name" }, b.department));
    if (b.limit == null) {
      row.appendChild(el("div", { class: "muted" }, "No budget set. Spent " + money(b.spent) + " this month."));
    } else {
      const bar = el("div", { class: "bar" }), fill = el("span", { class: b.state });
      fill.style.width = Math.min(b.percent, 100) + "%"; bar.appendChild(fill); row.appendChild(bar);
      row.appendChild(el("div"));
      const line = el("div", {}, money(b.spent) + " of " + money(b.limit) + " (" + b.percent + "%), " + money(b.remaining) + " left. ");
      line.appendChild(el("strong", { class: "status-" + b.state }, BADGE[b.state]));
      row.appendChild(line);
    }
    box.appendChild(row);
  });
}

// ---- charts
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}
function frame(W, H, M, max, fmt) {
  const s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img" });
  const grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
  for (let i = 0; i <= 4; i++) {
    const y = M.t + (H - M.t - M.b) * (1 - i / 4);
    grid.appendChild(svg("line", { x1: M.l, x2: W - M.r, y1: y, y2: y }));
    axis.appendChild(svg("text", { x: M.l - 6, y: y + 4, "text-anchor": "end" }, fmt(max * i / 4)));
  }
  s.append(grid, axis); return { s, axis };
}
function xLabels(axis, days, xOf, W, H, M) {
  const step = Math.max(1, Math.ceil(days.length / 8));
  days.forEach((d, i) => { if (i % step === 0) axis.appendChild(svg("text", { x: xOf(i), y: H - M.b + 16, "text-anchor": "middle" }, d.slice(5))); });
}
function emptyChart(box, text) { box.replaceChildren(el("div", { class: "empty" }, text)); }

function groupDepartments(daily) {
  const totals = {};
  daily.forEach((r) => { totals[r.department] = (totals[r.department] || 0) + r.cost_usd + r.requests * 1e-9; });
  let names = Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
  let keep = names;
  if (names.length > PALETTE.length) keep = names.slice(0, PALETTE.length - 1);
  const folded = (n) => keep.includes(n) ? n : "Other";
  const order = keep.slice().sort(); if (names.length > keep.length) order.push("Other");
  return { order, folded };
}

function renderCost(daily) {
  const box = $("chart-cost"), legend = $("legend-cost"); legend.replaceChildren();
  if (!daily.length) { emptyChart(box, "No requests in this period."); return; }
  const { order, folded } = groupDepartments(daily);
  const days = [...new Set(daily.map((r) => r.day))].sort();
  const cell = {}; daily.forEach((r) => { const k = r.day + "|" + folded(r.department); const c = cell[k] || (cell[k] = { cost: 0, n: 0 }); c.cost += r.cost_usd; c.n += r.requests; });
  const totals = days.map((d) => order.reduce((s, n) => s + ((cell[d + "|" + n] || {}).cost || 0), 0));
  const max = niceMax(Math.max.apply(null, totals)), W = 720, H = 280, M = { l: 56, r: 12, t: 12, b: 28 };
  const { s, axis } = frame(W, H, M, max, (v) => "$" + (max < 1 ? v.toFixed(3) : v.toFixed(2)));
  const band = (W - M.l - M.r) / days.length, bw = Math.min(30, band * 0.62);
  const xOf = (i) => M.l + band * (i + 0.5), yOf = (v) => M.t + (H - M.t - M.b) * (1 - v / max);
  days.forEach((d, i) => {
    let acc = 0;
    order.forEach((n, j) => {
      const c = cell[d + "|" + n]; if (!c || c.cost <= 0) return;
      const y1 = yOf(acc + c.cost), y0 = yOf(acc); acc += c.cost;
      const r = svg("rect", { x: xOf(i) - bw / 2, y: y1, width: bw, height: Math.max(y0 - y1, 1), rx: 2, fill: cssVar(PALETTE[j]), stroke: cssVar("--surface"), "stroke-width": 2 });
      r.addEventListener("mousemove", (e) => showTip(e, d + " | " + n + " | " + money(c.cost) + " | " + c.n + " requests"));
      r.addEventListener("mouseleave", hideTip); s.appendChild(r);
    });
  });
  xLabels(axis, days, xOf, W, H, M);
  box.replaceChildren(s);
  order.forEach((n, j) => { const li = el("span"); const sw = el("i"); sw.style.background = cssVar(PALETTE[j]); li.append(sw, document.createTextNode(n)); legend.appendChild(li); });
}

function renderRequests(daily) {
  const box = $("chart-requests");
  if (!daily.length) { emptyChart(box, "No requests in this period."); return; }
  const per = {}; daily.forEach((r) => { per[r.day] = (per[r.day] || 0) + r.requests; });
  const days = Object.keys(per).sort(), vals = days.map((d) => per[d]);
  const max = niceMax(Math.max.apply(null, vals)), W = 720, H = 220, M = { l: 56, r: 12, t: 12, b: 28 };
  const { s, axis } = frame(W, H, M, max, (v) => String(Math.round(v)));
  const xOf = (i) => days.length === 1 ? (W + M.l - M.r) / 2 : M.l + (W - M.l - M.r) * i / (days.length - 1);
  const yOf = (v) => M.t + (H - M.t - M.b) * (1 - v / max), colour = cssVar("--s1");
  s.appendChild(svg("polyline", { points: vals.map((v, i) => xOf(i) + "," + yOf(v)).join(" "), fill: "none", stroke: colour, "stroke-width": 2 }));
  vals.forEach((v, i) => {
    const c = svg("circle", { cx: xOf(i), cy: yOf(v), r: 4, fill: colour, stroke: cssVar("--surface"), "stroke-width": 2 });
    const hit = svg("circle", { cx: xOf(i), cy: yOf(v), r: 12, fill: "transparent" });
    hit.addEventListener("mousemove", (e) => showTip(e, days[i] + " | " + v + " requests")); hit.addEventListener("mouseleave", hideTip);
    s.append(c, hit);
  });
  xLabels(axis, days, xOf, W, H, M);
  box.replaceChildren(s);
}

// ---- everything
function render(d) {
  renderKpis(d.kpis); renderBudgets(d.budgets); renderCost(d.daily); renderRequests(d.daily);
  table($("t-outcomes"), [{ key: "outcome", label: "Outcome" }, { key: "status_code", label: "HTTP" }, { key: "requests", label: "Requests", num: 1, fmt: int }], d.outcomes);
  table($("t-models"), [{ key: "provider", label: "Provider" }, { key: "model", label: "Model" }, { key: "requests", label: "Requests", num: 1, fmt: int },
    { key: "cost_usd", label: "Cost", num: 1, fmt: money }, { key: "avg_latency_ms", label: "Avg ms", num: 1, fmt: (v) => v == null ? "-" : Math.round(v) }], d.by_model);
  table($("t-departments"), [{ key: "department", label: "Department" }, { key: "requests", label: "Requests", num: 1, fmt: int },
    { key: "tokens", label: "Tokens", num: 1, fmt: int }, { key: "cost_usd", label: "Cost", num: 1, fmt: money }], d.by_department);
  table($("t-users"), [{ key: "user", label: "User" }, { key: "department", label: "Department" }, { key: "requests", label: "Requests", num: 1, fmt: int },
    { key: "tokens", label: "Tokens", num: 1, fmt: int }, { key: "cost_usd", label: "Cost", num: 1, fmt: money }], d.by_user);
  table($("t-security"), [{ key: "rule", label: "Rule" }, { key: "action", label: "Action" }, { key: "matches", label: "Matches", num: 1, fmt: int },
    { key: "users", label: "Users", num: 1, fmt: int }], d.security, "The filter has not caught anything in this period.");
  table($("t-rules"), [{ key: "rule", label: "Rule" }, { key: "action", label: "Action" }],
    Object.keys(d.rules).map((r) => ({ rule: r, action: d.rules[r] })));
  table($("t-audit"), [{ key: "created_at", label: "Time", fmt: when }, { key: "user_name", label: "User" }, { key: "department", label: "Department" },
    { key: "rule", label: "Rule" }, { key: "match_count", label: "Count", num: 1 }, { key: "action", label: "Action" }, { key: "provider", label: "Provider" }], d.audit, "No audit entries yet.");
  table($("t-requests"), [{ key: "time", label: "Time", fmt: when }, { key: "user", label: "User" }, { key: "provider", label: "Provider" }, { key: "model", label: "Model" },
    { key: "tokens", label: "Tokens", num: 1, fmt: int }, { key: "cost_usd", label: "Cost", num: 1, fmt: money }, { key: "status", label: "HTTP", num: 1 },
    { key: "latency_ms", label: "ms", num: 1 }, { key: "error", label: "Error" }], d.requests, "No requests yet.");
}

let timer = null;
async function load() {
  const err = $("error");
  try {
    const r = await fetch("/dashboard/api/summary?days=" + encodeURIComponent($("days").value), { cache: "no-store" });
    if (r.status === 401) { location.replace("/dashboard/login"); return; }
    if (!r.ok) throw new Error("The server answered HTTP " + r.status + ".");
    render(await r.json()); err.hidden = true;
    $("updated").textContent = "Updated " + new Date().toLocaleTimeString();
  } catch (e) {
    err.textContent = "Could not load the numbers: " + e.message; err.hidden = false;
  }
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  document.querySelectorAll(".tab").forEach((t) => { t.hidden = t.id !== "tab-" + b.dataset.tab; });
  if (b.dataset.tab === "manage") loadManage();
}));
$("days").addEventListener("change", load);
$("refresh").addEventListener("click", load);
$("auto").addEventListener("change", () => { clearInterval(timer); if ($("auto").checked) timer = setInterval(load, 30000); });

// ================================================================ account
async function post(path, body) {
  const r = await fetch("/dashboard/api" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (r.status === 401) { location.replace("/dashboard/login"); throw new Error("Please sign in."); }
  let data = {};
  try { data = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "That input is not valid.");
  return data;
}

$("logout").addEventListener("click", async () => {
  try { await post("/logout"); } catch (e) { /* leaving anyway */ }
  location.replace("/dashboard/login");
});

const pwDialog = $("password-dialog");
$("open-password").addEventListener("click", () => { $("form-password").reset(); $("pw-error").hidden = true; pwDialog.showModal(); });
$("pw-cancel").addEventListener("click", () => pwDialog.close());
$("form-password").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("pw-error"); err.hidden = true;
  if ($("pw-new").value !== $("pw-new2").value) { err.textContent = "The two new passwords are not the same."; err.hidden = false; return; }
  try {
    await post("/password", { old_password: $("pw-old").value, new_password: $("pw-new").value });
    pwDialog.close(); notify("Password changed. Other sessions were signed out.", true);
  } catch (e) { err.textContent = e.message; err.hidden = false; }
});

// ================================================================ manage
function notify(text, good) {
  const m = $("manage-msg"); m.textContent = text; m.className = "msg " + (good ? "good" : "bad"); m.hidden = false;
}
function showKey(user, key) {
  $("key-title").textContent = "API key for " + user;
  $("key-value").textContent = key; $("keybox").hidden = false;
  $("keybox").scrollIntoView({ block: "nearest" });
}
$("key-copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("key-value").textContent); notify("Key copied to the clipboard.", true); }
  catch (e) { notify("Could not copy. Select the key and press Ctrl+C.", false); }
});
$("key-close").addEventListener("click", () => { $("keybox").hidden = true; $("key-value").textContent = ""; });

async function act(fn, okText) {
  try { const res = await fn(); if (okText) notify(okText, true); await loadManage(); if (res && res.key) showKey(res.user, res.key); }
  catch (e) { notify(e.message, false); }
}
function button(label, onclick, cls) { const b = el("button", { type: "button", class: "small " + (cls || "") }, label); b.addEventListener("click", onclick); return b; }

function renderDepartments(d) {
  const box = $("m-departments"); box.replaceChildren();
  if (!d.departments.length) { box.appendChild(el("p", { class: "muted" }, "No departments yet. Add one below.")); return; }
  const t = el("table"), head = el("tr");
  ["Department", "Allowed providers", "Monthly budget (USD)", "Spent this month"].forEach((h) => head.appendChild(el("th", {}, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  d.departments.forEach((dep) => {
    const tr = el("tr");
    tr.appendChild(el("td", {}, dep.name));
    const prov = el("td"), pbox = el("div", { class: "inline" });
    d.providers.forEach((p) => {
      const lab = el("label", { class: "plain" });
      const cb = el("input", { type: "checkbox" }); cb.checked = dep.providers.includes(p);
      cb.addEventListener("change", () => act(() => post("/access", { department: dep.name, provider: p, allowed: cb.checked }), dep.name + ": " + p + (cb.checked ? " allowed." : " blocked.")));
      lab.append(cb, document.createTextNode(p)); pbox.appendChild(lab);
    });
    prov.appendChild(pbox); tr.appendChild(prov);
    const bud = el("td"), bbox = el("div", { class: "inline" });
    const input = el("input", { type: "number", min: "0", step: "0.01", placeholder: "no limit" }); if (dep.budget != null) input.value = dep.budget;
    bbox.append(input, button("Save", () => act(() => post("/budgets", { department: dep.name, monthly_limit_usd: input.value === "" ? null : Number(input.value) }), "Budget saved for " + dep.name + ".")));
    bud.appendChild(bbox); tr.appendChild(bud);
    tr.appendChild(el("td", {}, money(dep.spent) + (dep.state === "exceeded" ? "  ⛔ budget used up" : dep.state === "warning" ? "  ⚠️ over 80%" : "")));
    body.appendChild(tr);
  });
  t.appendChild(body); box.appendChild(t);
  const sel = $("new-user-dept"), keep = sel.value; sel.replaceChildren();
  d.departments.forEach((dep) => sel.appendChild(el("option", { value: dep.name }, dep.name)));
  if (keep) sel.value = keep;
}

function renderUsers(d) {
  const box = $("m-users"); box.replaceChildren();
  if (!d.users.length) { box.appendChild(el("p", { class: "muted" }, "No users yet. Add one below.")); return; }
  const t = el("table"), head = el("tr");
  ["User", "Department", "Status", "Active keys", "Actions"].forEach((h) => head.appendChild(el("th", {}, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  d.users.forEach((u) => {
    const tr = el("tr");
    tr.appendChild(el("td", {}, u.user)); tr.appendChild(el("td", {}, u.department));
    tr.appendChild(el("td", {}, u.active ? "✅ active" : "⛔ disabled"));
    const keys = el("td");
    (u.key_prefixes ? u.key_prefixes.split(",").map((x) => x.trim()) : []).forEach((p) => {
      const pill = el("span", { class: "pill" }, p + "…");
      pill.appendChild(button("Revoke", () => { if (confirm("Revoke key " + p + "… ? Anyone using it will be refused.")) act(() => post("/keys/revoke", { prefix: p }), "Key revoked."); }, "danger"));
      keys.appendChild(pill);
    });
    if (!u.active_keys) keys.appendChild(el("span", { class: "muted" }, "none"));
    tr.appendChild(keys);
    const actions = el("td"), abox = el("div", { class: "inline" });
    abox.append(
      button("New key", () => act(() => post("/users/" + encodeURIComponent(u.user) + "/keys", { replace: false }), "Key created.")),
      button("Replace key", () => { if (confirm("Revoke all keys of " + u.user + " and create a new one?")) act(() => post("/users/" + encodeURIComponent(u.user) + "/keys", { replace: true }), "Old keys revoked, new key created."); }),
      button(u.active ? "Disable" : "Enable", () => act(() => post("/users/" + encodeURIComponent(u.user) + "/active", { active: !u.active }), u.user + (u.active ? " disabled." : " enabled.")), u.active ? "danger" : ""));
    actions.appendChild(abox); tr.appendChild(actions); body.appendChild(tr);
  });
  t.appendChild(body); box.appendChild(t);
}

function renderRules(d) {
  const box = $("m-rules"); box.replaceChildren();
  const t = el("table"), head = el("tr");
  ["Rule", "What happens when found"].forEach((h) => head.appendChild(el("th", {}, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  Object.keys(d.rules).forEach((rule) => {
    const tr = el("tr"), sel = el("select");
    [["mask", "mask (replace with a placeholder)"], ["block", "block (refuse the request)"], ["off", "off (ignore)"]].forEach(([v, l]) => sel.appendChild(el("option", { value: v }, l)));
    sel.value = d.rules[rule];
    sel.addEventListener("change", () => act(() => post("/rules", { rule: rule, action: sel.value }), "Rule '" + rule + "' is now '" + sel.value + "'."));
    tr.appendChild(el("td", {}, rule)); const td = el("td"); td.appendChild(sel); tr.appendChild(td); body.appendChild(tr);
  });
  t.appendChild(body); box.appendChild(t);
}

async function loadManage() {
  try {
    const r = await fetch("/dashboard/api/manage", { cache: "no-store" });
    if (r.status === 401) { location.replace("/dashboard/login"); return; }
    if (!r.ok) throw new Error("The server answered HTTP " + r.status + ".");
    const d = await r.json();
    renderDepartments(d); renderUsers(d); renderRules(d);
    table($("m-actions"), [{ key: "created_at", label: "Time", fmt: when }, { key: "admin_name", label: "Admin" }, { key: "action", label: "Action" }, { key: "detail", label: "Details" }], d.actions, "Nothing yet.");
  } catch (e) { notify("Could not load the management data: " + e.message, false); }
}

$("form-department").addEventListener("submit", (ev) => {
  ev.preventDefault();
  act(() => post("/departments", { name: $("new-department").value }), "Department added.").then(() => { $("new-department").value = ""; });
});
$("form-user").addEventListener("submit", (ev) => {
  ev.preventDefault();
  act(() => post("/users", { name: $("new-user").value, department: $("new-user-dept").value }), "User created. Copy the key below now.").then(() => { $("new-user").value = ""; });
});

// ================================================================ start
(async function start() {
  try {
    const info = await (await fetch("/dashboard/api/session", { cache: "no-store" })).json();
    if (!info.authenticated) { location.replace("/dashboard/login"); return; }
    $("admin-name").textContent = info.username;
  } catch (e) { /* load() reports the problem */ }
  load();
})();

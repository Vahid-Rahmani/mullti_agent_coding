"use strict";
/* Phase 3 Model Selection UI tests — run with
   `node test/tests/workspace_model_selection.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   the ranked recommendation list behind the Model picker:

     A. renderModelRecommendation POSTs /api/models/recommend with the node's
        task / prompt_profile / explicit_model
     B. ranked items render name + % match + reason
     C. an explicit model is listed first, flagged, and never overwritten
     D. Apply sets n.model (persists into the workflow node) and marks dirty
     E. Auto mode (no node.model) shows an "Auto will use" hint and never
        mutates the node
     F. the provider filter re-fetches with the chosen provider
     G. a failed fetch shows an error hint and never throws
*/

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const WS_JS = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "workspace.js");
const src = fs.readFileSync(WS_JS, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function eq(a, b, msg) { count += 1; assert.strictEqual(a, b, msg); }

function makeEl(tag) {
  return {
    tagName: tag,
    children: [],
    className: "",
    textContent: "",
    title: "",
    value: "",
    type: "",
    dataset: {},
    style: {},
    attrs: {},
    parentNode: null,
    _handlers: {},
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, on) {
        if (on === undefined) on = !this._s.has(c);
        on ? this._s.add(c) : this._s.delete(c);
        return on;
      },
      contains(c) { return this._s.has(c); },
    },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); },
    dispatch(type, ev) { (this._handlers[type] || []).forEach((fn) => fn(ev || {})); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {},
    get firstChild() { return this.children[0] || null; },
  };
}

const registry = {
  "ws-status": makeEl("div"),
  "ws-dirty": makeEl("div"),
  "ws-activate": makeEl("button"),
  "ws-workflow-select": makeEl("select"),
  "ws-template-select": makeEl("select"),
  "ws-props-body": makeEl("div"),
  "ws-world": makeEl("div"),
  "ws-edges": makeEl("svg"),
  "ws-nodes": makeEl("div"),
  "ws-canvas": makeEl("div"),
  "ws-empty-hint": makeEl("div"),
  "ws-library-list": makeEl("div"),
};

const document = {
  readyState: "loading",
  title: "",
  addEventListener() {},
  querySelector(sel) {
    if (sel && sel[0] === "#") return registry[sel.slice(1)] || null;
    return null;
  },
  querySelectorAll() { return []; },
  createElement: (t) => makeEl(t),
  createElementNS: () => makeEl("g"),
};

global.window = {
  addEventListener() {},
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  prompt() { return null; },
  confirm() { return false; },
};
global.document = document;
global.requestAnimationFrame = (cb) => { cb(); return 0; };

/* ── fetch stub ────────────────────────────────────────────────── */
let requests = [];
let fetchImpl = null;
global.fetch = async (p, opts) => {
  requests.push({ path: p, opts });
  if (!fetchImpl) throw new Error("no fetch handler registered");
  return fetchImpl(p, opts);
};
function jsonRes(status, data) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => data,
  };
}

eval(src); // IIFE runs; init() is NOT called (readyState === "loading")

const { S, renderModelRecommendation } = global.window.MACWorkspace;

// model registry metadata so display names resolve
S.modelCatalog = [
  { id: "opencode/deepseek-v4-flash-free", display_name: "DeepSeek V4 Flash (free)", provider: "opencode" },
  { id: "opencode/big-pickle", display_name: "Big Pickle", provider: "opencode" },
  { id: "google/gemini-3.6-flash", display_name: "Gemini 3.6 Flash", provider: "google" },
];
S.modelById = {};
S.modelCatalog.forEach((m) => { S.modelById[m.id] = m; });

function body() { return makeEl("div"); }
const tick = () => new Promise((r) => setTimeout(r, 0));

const RECS = {
  requirements: { reasoning: "high", coding: "high" },
  recommendations: [
    { model_id: "opencode/big-pickle", score: 0.94, reason: "meets reasoning, coding, context", explicit: false },
    { model_id: "google/gemini-3.6-flash", score: 0.87, reason: "meets reasoning, coding", explicit: false },
  ],
};

async function main() {
  /* ── A: request payload carries the node's task/prompt/explicit model ── */
  const n = { id: "n1", agent: "matthew", kind: "agent",
              prompt_profile: "software-engineer-expert",
              task: { description: "refactor the auth module" },
              model: "" };
  fetchImpl = async (p, opts) => {
    if (p === "/api/models/recommend") {
      return jsonRes(200, JSON.parse(JSON.stringify(RECS)));
    }
    throw new Error("unexpected fetch: " + p);
  };
  const b = body();
  renderModelRecommendation(b, n);
  await tick();
  const recReq = requests.find((r) => r.path === "/api/models/recommend");
  ok(recReq, "A: recommendation request issued");
  const sent = JSON.parse(recReq.opts.body);
  eq(sent.task, "refactor the auth module", "A: task description sent");
  eq(sent.prompt_profile, "software-engineer-expert", "A: prompt_profile sent");
  eq(sent.explicit_model, undefined, "A: empty model → no explicit_model (Auto)");
  eq(sent.provider, undefined, "A: no provider filter by default");

  /* ── B: ranked items render name + % + reason ── */
  const wrapB = b.children.find((c) => c.className === "ws-model-recs");
  ok(wrapB, "B: recommendation block rendered");
  const listEl = wrapB.children.find((c) => c.className === "ws-model-recs-list");
  ok(listEl, "B: recommendation list rendered");
  const items = listEl.children.filter((c) => c.className.startsWith("ws-model-rec-item"));
  eq(items.length, 2, "B: two ranked items");
  eq(items[0].children[0].children[0].textContent, "Big Pickle", "B: top item name");
  eq(items[0].children[0].children[1].textContent, "94% match", "B: top item score");
  eq(items[0].children[1].textContent, "meets reasoning, coding, context", "B: reason shown");

  /* ── E: Auto mode shows the hint and never mutates the node ── */
  const hints = listEl.children.filter((c) => c.className === "ws-model-recs-hint");
  const autoHint = hints[hints.length - 1];
  ok(/Auto will use: Big Pickle/.test(autoHint.textContent), "E: Auto hint names the top pick");
  eq(n.model, "", "E: Auto mode never writes a model to the node");

  /* ── C: explicit model is first, flagged, never overwritten ── */
  const expNode = { id: "n2", agent: "alex", kind: "agent",
                    prompt_profile: "software-engineer-expert", model: "google/gemini-3.6-flash" };
  fetchImpl = async (p) => {
    if (p === "/api/models/recommend") {
      return jsonRes(200, {
        requirements: {},
        recommendations: [
          { model_id: "google/gemini-3.6-flash", score: 0.87, reason: "explicit", explicit: true },
          { model_id: "opencode/big-pickle", score: 0.94, reason: "meets reasoning", explicit: false },
        ],
      });
    }
    throw new Error("unexpected fetch: " + p);
  };
  const b2 = body();
  renderModelRecommendation(b2, expNode);
  await tick();
  const wrap2 = b2.children.find((c) => c.className === "ws-model-recs");
  const items2 = wrap2.children.find((c) => c.className === "ws-model-recs-list").children
    .filter((c) => c.className.startsWith("ws-model-rec-item"));
  eq(items2[0].className.includes("explicit"), true, "C: explicit item flagged");
  eq(items2[0].children[0].children[0].textContent, "Gemini 3.6 Flash", "C: explicit listed first");
  ok(/explicit selection/.test(items2[0].children[2].textContent), "C: preservation note shown");
  eq(expNode.model, "google/gemini-3.6-flash", "C: node model untouched by recommendations");

  /* ── D: Apply sets the node model + marks dirty ── */
  const applyNode = { id: "n3", agent: "sarah", kind: "agent", model: "" };
  fetchImpl = async (p) => {
    if (p === "/api/models/recommend") {
      return jsonRes(200, JSON.parse(JSON.stringify(RECS)));
    }
    throw new Error("unexpected fetch: " + p);
  };
  const b3 = body();
  S.workflow = { id: "w", nodes: [applyNode], edges: [], entry: [], state: {}, settings: {} };
  S.dirty = false;
  renderModelRecommendation(b3, applyNode);
  await tick();
  const wrap3 = b3.children.find((c) => c.className === "ws-model-recs");
  const items3 = wrap3.children.find((c) => c.className === "ws-model-recs-list").children
    .filter((c) => c.className.startsWith("ws-model-rec-item"));
  const applyBtn = items3[0].children.find((c) => String(c.className).includes("ws-model-rec-apply"));
  ok(applyBtn, "D: Apply button rendered for a non-selected recommendation");
  applyBtn.dispatch("click");
  eq(applyNode.model, "opencode/big-pickle", "D: Apply persists the model onto the node");
  eq(S.dirty, true, "D: Apply marks the workflow dirty");

  /* ── F: provider filter re-fetches with the provider ── */
  fetchImpl = async (p, opts) => {
    if (p === "/api/models/recommend") {
      return jsonRes(200, JSON.parse(JSON.stringify(RECS)));
    }
    throw new Error("unexpected fetch: " + p);
  };
  const b4 = body();
  renderModelRecommendation(b4, { id: "n4", agent: "david", kind: "agent", model: "" });
  await tick();
  const wrap4 = b4.children.find((c) => c.className === "ws-model-recs");
  const provSel = wrap4.children.find((c) => c.className === "ws-model-provider");
  provSel.value = "google";
  provSel.dispatch("change");
  await tick();
  const lastReq = requests.filter((r) => r.path === "/api/models/recommend").pop();
  eq(JSON.parse(lastReq.opts.body).provider, "google", "F: provider filter passed through");

  /* ── G: failed fetch shows an error hint without throwing ── */
  fetchImpl = async (p) => {
    if (p === "/api/models/recommend") {
      return jsonRes(500, { detail: "boom" });
    }
    throw new Error("unexpected fetch: " + p);
  };
  const b5 = body();
  renderModelRecommendation(b5, { id: "n5", agent: "elena", kind: "agent", model: "" });
  await tick();
  const wrap5 = b5.children.find((c) => c.className === "ws-model-recs");
  const list5 = wrap5.children.find((c) => c.className === "ws-model-recs-list");
  ok(/unavailable/.test(list5.children[0].textContent), "G: failure hint shown");
  eq(list5.children[0].className, "ws-model-recs-hint", "G: hint styling");

  console.log("workspace model selection tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

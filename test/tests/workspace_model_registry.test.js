"use strict";
/* Phase 3 Model Registry UI tests — run with
   `node test/tests/workspace_model_registry.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   the provider-neutral registry catalog + model-details preview:

     A. loadModelCatalog fetches /api/models and populates S.modelCatalog/ById
     B. modelProviderOptions returns sorted distinct providers
     C. modelDisplayName prefers display_name and falls back to the id
     D. renderModelDetails renders the compact metadata table for a known model
     E. renderModelDetails renders nothing for an unknown/empty model (no throw)
     F. the catalog is metadata only — it never mutates a workflow node
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

const { S, loadModelCatalog, modelProviderOptions, modelDisplayName,
        renderModelDetails } = global.window.MACWorkspace;

const CATALOG = {
  models: [
    { id: "opencode/deepseek-v4-flash-free", display_name: "DeepSeek V4 Flash (free)",
      provider: "opencode", family: "deepseek", context_window: 128000,
      capabilities: { reasoning: "high", coding: "high", tool_use: "high",
                      vision: "low", latency: "medium", cost: "low",
                      structured_output: "high" } },
    { id: "google/gemini-3.6-flash", display_name: "Gemini 3.6 Flash",
      provider: "google", family: "gemini", context_window: 128000,
      capabilities: { reasoning: "high", coding: "high", tool_use: "high",
                      vision: "high", latency: "medium", cost: "low",
                      structured_output: "high" } },
    { id: "openai/gpt-5", display_name: "GPT-5 (catalog)",
      provider: "openai", family: "gpt", context_window: 200000,
      capabilities: { reasoning: "high", coding: "high", tool_use: "high",
                      vision: "high", latency: "medium", cost: "high",
                      structured_output: "high" } },
  ],
  providers: ["google", "opencode", "openai"],
};

function body() { return makeEl("div"); }

async function main() {
  /* ── A: loadModelCatalog populates the catalog + id lookup ── */
  fetchImpl = async (p) => {
    if (p === "/api/models") return jsonRes(200, JSON.parse(JSON.stringify(CATALOG)));
    throw new Error("unexpected fetch: " + p);
  };
  await loadModelCatalog();
  eq(S.modelCatalog.length, 3, "A: catalog loaded");
  eq(S.modelById["google/gemini-3.6-flash"].provider, "google", "A: id lookup built");
  eq(requests[requests.length - 1].path, "/api/models", "A: fetched /api/models");

  /* ── B: provider options are sorted and distinct ── */
  eq(JSON.stringify(modelProviderOptions()), '["google","openai","opencode"]',
     "B: providers sorted (lexicographic), no duplicates");

  /* ── C: display name resolution ── */
  eq(modelDisplayName("google/gemini-3.6-flash"), "Gemini 3.6 Flash", "C: uses display_name");
  eq(modelDisplayName("custom/not-in-catalog"), "custom/not-in-catalog", "C: falls back to id");

  /* ── D: model details table for a known model ── */
  const n = { id: "n1", agent: "matthew", kind: "agent", model: "google/gemini-3.6-flash" };
  const b = body();
  renderModelDetails(b, n);
  const wrap = b.children.find((c) => c.className === "ws-model-details");
  ok(wrap, "D: details block rendered");
  eq(wrap.children[0].textContent, "Model details", "D: title");
  const rows = wrap.children.slice(1);
  const byLabel = {};
  rows.forEach((r) => { byLabel[r.children[0].textContent] = r.children[1].textContent; });
  eq(byLabel["Provider"], "google", "D: provider row");
  eq(byLabel["Family"], "gemini", "D: family row");
  eq(byLabel["Context"], "128,000 tokens", "D: context row");
  eq(byLabel["Reasoning"], "High", "D: reasoning row");
  eq(byLabel["Coding"], "High", "D: coding row");
  eq(byLabel["Tool use"], "High", "D: tool use row");
  eq(byLabel["Vision"], "High", "D: vision row");
  eq(byLabel["Structured output"], "High", "D: structured output row");
  eq(byLabel["Latency"], "Medium", "D: latency row");
  eq(byLabel["Cost tier"], "Low", "D: cost tier row");

  /* ── E: unknown / empty model renders nothing (no throw) ── */
  const b2 = body();
  renderModelDetails(b2, { id: "n2", agent: "alex", kind: "agent", model: "no/such-model" });
  eq(b2.children.length, 0, "E: unknown model → no details block");
  const b3 = body();
  renderModelDetails(b3, { id: "n3", agent: "alex", kind: "agent", model: "" });
  eq(b3.children.length, 0, "E: Auto (no model) → no details block");

  /* ── F: catalog lookups never mutate the node ── */
  const before = JSON.stringify(n);
  renderModelDetails(body(), n);
  eq(JSON.stringify(n), before, "F: registry/details are read-only for the node");

  console.log("workspace model registry tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

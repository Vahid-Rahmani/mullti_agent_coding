"use strict";
/* Phase 2 Model recommendation behavioral tests — run with
   `node test/tests/workspace_model_recommendation.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   the provider-neutral "Model requirements" preview:

     A. a selected prompt profile with model_preferences renders a table
     B. the table rows carry the exact provider-neutral labels in fixed order
     C. values are capitalized for display
     D. a profile with no model_preferences renders nothing
     E. an unknown profile id renders nothing (no throw)
     F. the user's explicit model is never changed by the preview
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
    label: "",
    type: "",
    dataset: {},
    style: {},
    hidden: false,
    clientWidth: 800,
    clientHeight: 600,
    parentNode: null,
    attrs: {},
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
    contains() { return false; },
    focus() {},
    getBoundingClientRect() { return { left: 0, top: 0 }; },
    get firstChild() { return this.children[0] || null; },
  };
}

const registry = {
  "ws-status": makeEl("div"),
  "ws-dirty": makeEl("div"),
  "ws-activate": makeEl("button"),
  "ws-workflow-select": makeEl("select"),
  "ws-template-select": makeEl("select"),
  "ws-template-load": makeEl("button"),
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
global.fetch = async () => { throw new Error("no fetch expected"); };

eval(src);

const { S, renderModelCapabilityPreview } = global.window.MACWorkspace;

function body() { return makeEl("div"); }

async function main() {
  /* ── A/B/C: a profile with model_preferences renders a labelled table ── */
  S.promptById = {
    "software-engineer-expert": {
      id: "software-engineer-expert", name: "Expert Software Engineer",
      model_preferences: { reasoning: "high", coding: "high", tool_use: "high",
                           context: "large", latency: "medium", cost: "medium" },
    },
  };
  const n = { id: "n1", agent: "matthew", kind: "agent",
              prompt_profile: "software-engineer-expert",
              model: "google/gemini-3.5-flash-lite" };
  const b = body();
  renderModelCapabilityPreview(b, n);
  const wrap = b.children.find((c) => c.className === "ws-model-prefs");
  ok(wrap, "A: model-requirements block rendered");
  eq(wrap.children[0].textContent, "Model requirements", "A: title rendered");
  const table = wrap.children[1];
  eq(table.className, "ws-model-prefs-table", "A: table rendered");

  const expected = [
    ["Reasoning", "High"],
    ["Coding", "High"],
    ["Tool use", "High"],
    ["Context", "Large"],
    ["Latency", "Medium"],
    ["Cost", "Medium"],
  ];
  eq(table.children.length, expected.length, "B: six requirement rows");
  table.children.forEach((row, i) => {
    eq(row.children[0].textContent, expected[i][0], "B: label " + i);
    eq(row.children[1].textContent, expected[i][1], "C: value " + i);
  });

  /* ── D: profile without model_preferences renders nothing ── */
  S.promptById["no-prefs"] = { id: "no-prefs", name: "No Prefs" };
  const n2 = { id: "n2", agent: "alex", kind: "agent", prompt_profile: "no-prefs" };
  const b2 = body();
  renderModelCapabilityPreview(b2, n2);
  eq(b2.children.length, 0, "D: no model_preferences → no block");

  /* ── E: unknown profile id renders nothing (no throw) ── */
  const n3 = { id: "n3", agent: "alex", kind: "agent", prompt_profile: "missing-id" };
  const b3 = body();
  renderModelCapabilityPreview(b3, n3);
  eq(b3.children.length, 0, "E: unknown profile → no block");

  /* ── F: the user's explicit model is never changed ── */
  eq(n.model, "google/gemini-3.5-flash-lite",
     "F: preview never mutates the node's explicit model");

  console.log("workspace model recommendation tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

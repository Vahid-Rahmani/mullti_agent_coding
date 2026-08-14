"use strict";
/* Workflow Designer → template loading behavioral tests — run with
   `node test/tests/workspace_template.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   loadTemplate() + recalcNid() wire into the existing GET
   /api/workflows/from-template/{name} contract:

     A. loadTemplate issues GET /api/workflows/from-template/{name}
     B. the returned workflow fully replaces S.workflow (never a merge)
     C. run state (runStatuses/waves) is reset
     D. the node-id counter is recalculated (recalcNid)
     E. the previous workflow on disk can't be overwritten (no PUT/save)
     F. a template load failure surfaces the API error, graph unchanged
     G. an empty template selection makes no request
*/

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "workspace.js");
const src = fs.readFileSync(SRC, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function eq(a, b, msg) { count += 1; assert.strictEqual(a, b, msg); }

/* ── minimal DOM shim ──────────────────────────────────────────── */
function makeEl() {
  return {
    textContent: "",
    className: "",
    title: "",
    value: "",
    innerHTML: "",
    style: {},
    dataset: {},
    hidden: false,
    clientWidth: 800,
    clientHeight: 600,
    attrs: {},
    firstChild: null,
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
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener() {},
    appendChild() {},
    removeChild() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

const registry = {
  "ws-status": makeEl(),
  "ws-dirty": makeEl(),
  "ws-activate": makeEl(),
  "ws-workflow-select": makeEl(),
  "ws-template-select": makeEl(),
  "ws-template-load": makeEl(),
  "ws-props-body": makeEl(),
  "ws-world": makeEl(),
  "ws-edges": makeEl(),
  "ws-nodes": makeEl(),
  "ws-canvas": makeEl(),
  "ws-empty-hint": makeEl(),
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
  createElement() { return makeEl(); },
  createElementNS() { return makeEl(); },
};

global.window = {
  addEventListener() {},
  localStorage: {
    _s: {},
    setItem(k, v) { this._s[k] = v; },
    getItem(k) { return this._s[k] || null; },
    removeItem(k) { delete this._s[k]; },
  },
  prompt() { return null; },
  confirm() { return false; },
};
global.document = document;
// fitToScreen runs via requestAnimationFrame after load; run it synchronously
// so the camera/centering assertions observe the fitted state.
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
function reset() {
  requests = [];
  fetchImpl = null;
  registry["ws-status"].textContent = "";
  registry["ws-status"].className = "";
}

eval(src); // IIFE runs; init() is NOT called (readyState === "loading")

const { S, loadTemplate, recalcNid } = global.window.MACWorkspace;

const PARALLEL = {
  id: "template-parallel", name: "Parallel Engineering", project: "",
  nodes: [
    { id: "architect", label: "Architect", agent: "matthew", kind: "agent", x: 0, y: 0, model: "", roles: [] },
    { id: "backend", label: "Backend", agent: "alex", kind: "agent", x: 160, y: -120, model: "", roles: [] },
    { id: "frontend", label: "Frontend", agent: "sarah", kind: "agent", x: 160, y: 0, model: "", roles: [] },
    { id: "reviewer", label: "Reviewer", agent: "david", kind: "agent", x: 320, y: 0, model: "", roles: [] },
  ],
  edges: [
    { source: "architect", target: "backend", condition: "" },
    { source: "architect", target: "frontend", condition: "" },
    { source: "backend", target: "reviewer", condition: "" },
    { source: "frontend", target: "reviewer", condition: "" },
  ],
  entry: [], state: {}, settings: { max_iterations: 3 },
};

const PREVIOUS = {
  id: "my-pipeline", name: "My Pipeline", project: "",
  nodes: [{ id: "n1", label: "Old", agent: "matthew", kind: "agent", x: 0, y: 0, model: "" }],
  edges: [], entry: ["n1"], state: {}, settings: { max_iterations: 3 },
};

async function main() {
  /* ── A/B/C/E: GET, full replacement, run-state reset, no persistence ── */
  reset();
  S.workflow = JSON.parse(JSON.stringify(PREVIOUS));
  S.runStatuses = { n1: "running" };
  S.waves = { n1: 1 };
  S.selected = { type: "node", id: "n1" };
  registry["ws-template-select"].value = "parallel";
  fetchImpl = async (p, opts) => {
    if (p === "/api/workflows/from-template/parallel") {
      return jsonRes(200, { workflow: JSON.parse(JSON.stringify(PARALLEL)) });
    }
    throw new Error("unexpected fetch: " + p);
  };

  await loadTemplate();

  const req = requests[0];
  ok(req, "A: a from-template request was issued");
  eq(req.path, "/api/workflows/from-template/parallel", "A: POST hits the template endpoint");
  eq(req.opts.method, "POST", "A: request uses POST (matching the backend contract)");
  eq(requests.length, 1, "E: no save/PUT — the previous workflow is never persisted over");
  eq(S.workflow.id, "template-parallel", "B: S.workflow is fully replaced with the template");
  eq(S.workflow.nodes.length, 4, "B: template nodes replace the previous graph");
  ok(!S.workflow.nodes.some((n) => n.id === "n1"), "B: previous workflow nodes are gone (no merge)");
  eq(Object.keys(S.runStatuses).length, 0, "C: run statuses reset");
  eq(Object.keys(S.waves).length, 0, "C: waves reset");
  eq(S.selected.type, null, "C: selection cleared");
  eq(S.dirty, true, "C: loaded template is marked dirty (unsaved)");
  ok(/loaded/.test(registry["ws-status"].textContent), "C: success message shown");
  eq(registry["ws-status"].className, "ws-status ok", "C: success styling applied");

  /* ── template coords preserved + camera fitted ── */
  ok(PARALLEL.nodes.every((src, i) =>
        S.workflow.nodes[i].x === src.x && S.workflow.nodes[i].y === src.y),
     "template node coordinates are preserved verbatim (fitToScreen only pans/zooms)");
  ok(S.zoom >= 0.4 && S.zoom <= 1.5 && Number.isFinite(S.zoom),
     "fitToScreen ran: zoom clamped into [0.4, 1.5]");
  ok(S.tx !== 0 || S.ty !== 0, "fitToScreen ran: camera panned to center the graph");

  /* ── D: recalcNid avoids id collisions ── */
  S.workflow.nodes = [
    { id: "architect" }, { id: "n3" }, { id: "n7" }, { id: "developer" },
  ];
  recalcNid();
  eq(S.nid, 7, "D: counter tracks the largest numeric suffix (n7)");
  S.workflow.nodes = [{ id: "architect" }, { id: "developer" }];
  recalcNid();
  eq(S.nid, 2, "D: counter falls back to node count when no numeric ids exist");

  /* ── F: a failed load surfaces the API error and leaves the graph ── */
  reset();
  S.workflow = JSON.parse(JSON.stringify(PREVIOUS));
  const before = JSON.stringify(S.workflow);
  registry["ws-template-select"].value = "parallel";
  fetchImpl = async (p) => {
    if (p === "/api/workflows/from-template/parallel") {
      return jsonRes(404, { detail: "unknown template 'parallel'" });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await loadTemplate();
  eq(registry["ws-status"].textContent, "unknown template 'parallel'",
     "F: the actual API error is displayed");
  eq(registry["ws-status"].className, "ws-status err", "F: error styling applied");
  eq(JSON.stringify(S.workflow), before, "F: a failed load leaves the graph untouched");

  /* ── G: empty selection makes no request ── */
  reset();
  registry["ws-template-select"].value = "";
  fetchImpl = async () => { throw new Error("must not fetch"); };
  await loadTemplate();
  eq(requests.length, 0, "G: empty template selection issues no request");

  /* ── H: prompt_profile / task / model metadata survives template load ── */
  const RICH = {
    id: "template-rich", name: "Rich Template", project: "",
    nodes: [{
      id: "dev", label: "Dev", agent: "matthew", kind: "agent", x: 0, y: 0,
      model: "opencode/big-pickle",
      prompt_profile: "software-engineer-expert",
      task: { category: "development", capabilities: ["coding"] },
      roles: [],
    }],
    edges: [], entry: ["dev"], state: {}, settings: { max_iterations: 3 },
  };
  reset();
  registry["ws-template-select"].value = "rich";
  fetchImpl = async (p) => {
    if (p === "/api/workflows/from-template/rich") {
      return jsonRes(200, { workflow: JSON.parse(JSON.stringify(RICH)) });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await loadTemplate();
  const richNode = S.workflow.nodes[0];
  eq(richNode.model, "opencode/big-pickle", "H: node model preserved through template load");
  eq(richNode.prompt_profile, "software-engineer-expert", "H: prompt_profile preserved");
  eq(richNode.task.category, "development", "H: task metadata preserved");

  console.log("workspace template tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

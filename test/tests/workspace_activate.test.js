"use strict";
/* Workflow Designer → "Activate Workflow" behavioral tests — run with
   `node test/tests/workspace_activate.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   the Activate button wires into the existing /api/active-workflow contract:

     A. activate uses the currently loaded workflow id
     B. the exact PUT /api/active-workflow payload is { workflow_id }
     C. dirty workflows are saved BEFORE activation (never an outdated version)
     D. success is verified via GET and reflected as "✓ Active" in the UI
     E. a failed activation surfaces the API error and leaves the graph untouched
     F. an id-less/unsaved workflow shows a clear message and makes no requests
     G. the active indicator tracks which workflow is active (A vs B)
     H. an untitled workflow is saved with the prompted real id, then activated
     I. saveWorkflow() requires + adopts a real id (never persists "untitled")
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
    style: {},
    dataset: {},
    hidden: false,
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
    addEventListener() {},
    appendChild() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

const registry = {
  "ws-status": makeEl(),
  "ws-dirty": makeEl(),
  "ws-activate": makeEl(),
  "ws-workflow-select": makeEl(),
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
  registry["ws-activate"].textContent = "Activate Workflow";
  registry["ws-activate"].classList._s.clear();
}

eval(src); // IIFE runs; init() is NOT called (readyState === "loading")

const { S, activateWorkflow, updateActivateButton, refreshActiveIndicator,
        saveWorkflow } = global.window.MACWorkspace;

const WF_A = {
  id: "wf-a", name: "A",
  nodes: [{ id: "n1", agent: "matthew", kind: "agent", x: 100, y: 100, model: "" }],
  edges: [{ source: "n1", target: "n2", condition: "" },
          { source: "n2", target: "n3", condition: "success" }],
  entry: ["n1"], state: {}, settings: { max_iterations: 3 },
};

async function main() {
  /* ── A/B: correct id + exact payload + verify + UI reflection ── */
  reset();
  S.workflow = JSON.parse(JSON.stringify(WF_A));
  S.dirty = false;
  const before = JSON.stringify(S.workflow);
  fetchImpl = async (p, opts) => {
    if (p === "/api/active-workflow" && opts && opts.method === "PUT") {
      return jsonRes(200, { ok: true, active_workflow_id: "wf-a" });
    }
    if (p === "/api/active-workflow" && (!opts || !opts.method)) {
      return jsonRes(200, { active_workflow_id: "wf-a", workflow: { id: "wf-a" } });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await activateWorkflow();

  const putReq = requests.find((r) => r.path === "/api/active-workflow" && r.opts && r.opts.method === "PUT");
  ok(putReq, "A: PUT /api/active-workflow issued");
  const body = JSON.parse(putReq.opts.body);
  eq(Object.keys(body).join(","), "workflow_id", "B: payload has exactly the contract key");
  eq(body.workflow_id, "wf-a", "A: payload uses the currently loaded workflow id");
  const putIdx = requests.indexOf(putReq);
  const getReq = requests.slice(putIdx).find((r) => r.path === "/api/active-workflow" && (!r.opts || !r.opts.method));
  ok(getReq, "D: GET /api/active-workflow verification issued after PUT");
  eq(registry["ws-activate"].textContent, "✓ Active", "D: button reflects the active state");
  ok(registry["ws-activate"].classList.contains("active"), "D: button carries the active class");
  eq(registry["ws-status"].textContent, "✓ Active — Home projects this workflow", "D: status confirms activation");
  eq(JSON.stringify(S.workflow), before, "E: activation does not modify the workflow graph");

  /* ── C: dirty → save BEFORE activate ── */
  reset();
  S.workflow = JSON.parse(JSON.stringify(WF_A));
  S.dirty = true;
  fetchImpl = async (p, opts) => {
    if (p === "/api/workflows/wf-a" && opts && opts.method === "PUT") {
      return jsonRes(200, { ok: true, workflow: JSON.parse(JSON.stringify(S.workflow)) });
    }
    if (p === "/api/active-workflow" && opts && opts.method === "PUT") {
      return jsonRes(200, { ok: true, active_workflow_id: "wf-a" });
    }
    if (p === "/api/active-workflow" && (!opts || !opts.method)) {
      return jsonRes(200, { active_workflow_id: "wf-a" });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await activateWorkflow();
  const saveIdx = requests.findIndex((r) => r.path === "/api/workflows/wf-a");
  const actIdx = requests.findIndex((r) => r.path === "/api/active-workflow" && r.opts && r.opts.method === "PUT");
  ok(saveIdx >= 0, "C: dirty workflow is saved first");
  ok(actIdx > saveIdx, "C: save happens before activation (never an outdated version)");
  eq(S.dirty, false, "C: dirty flag cleared after the pre-activate save");

  /* ── E: failure surfaces the API error, graph untouched ── */
  reset();
  S.workflow = JSON.parse(JSON.stringify(WF_A));
  S.dirty = false;
  const beforeFail = JSON.stringify(S.workflow);
  fetchImpl = async (p, opts) => {
    if (p === "/api/active-workflow" && opts && opts.method === "PUT") {
      return jsonRes(409, { detail: "active workflow 'ghost' is missing — clear or re-activate it" });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await activateWorkflow();
  eq(registry["ws-status"].textContent,
     "active workflow 'ghost' is missing — clear or re-activate it",
     "E: the actual API error is displayed");
  eq(registry["ws-status"].className, "ws-status err", "E: error styling applied");
  eq(JSON.stringify(S.workflow), beforeFail, "E: a failed activation leaves the graph untouched");
  eq(registry["ws-activate"].textContent, "Activate Workflow", "E: button is not marked active on failure");

  /* ── F: untitled workflow → activate requires a real id (cancel → no requests) ── */
  reset();
  S.workflow = { id: "untitled", name: "", nodes: [], edges: [], entry: [], state: {}, settings: {} };
  S.dirty = false;
  global.window.prompt = () => null;   // user cancels the id prompt
  await activateWorkflow();
  eq(registry["ws-status"].textContent, "save cancelled — a workflow id is required",
     "F: canceling the id prompt shows a clear message");
  eq(requests.length, 0, "F: no API requests made when the id prompt is cancelled");

  /* ── G: the indicator tracks which workflow is active ── */
  reset();
  S.workflow = { id: "wf-b", name: "", nodes: [], edges: [], entry: [], state: {}, settings: {} };
  S.activeWorkflowId = "wf-a";   // a different workflow is active
  updateActivateButton();
  eq(registry["ws-activate"].textContent, "Activate Workflow", "G: not active when A is active and B is loaded");
  S.activeWorkflowId = "wf-b";
  updateActivateButton();
  eq(registry["ws-activate"].textContent, "✓ Active", "G: active indicator follows the active workflow id");

  /* ── H: untitled → prompt for a real id → save → activate ── */
  const WF_UNTITLED = {
    id: "untitled", name: "",
    nodes: [{ id: "n1", agent: "matthew", kind: "agent", x: 0, y: 0, model: "" }],
    edges: [], entry: ["n1"], state: {}, settings: { max_iterations: 3 },
  };
  reset();
  S.workflow = JSON.parse(JSON.stringify(WF_UNTITLED));
  S.dirty = false;
  global.window.prompt = () => "My Pipeline";   // user names the workflow
  fetchImpl = async (p, opts) => {
    if (p === "/api/workflows/my-pipeline" && opts && opts.method === "PUT") {
      const wf = JSON.parse(JSON.stringify(S.workflow));
      wf.id = "my-pipeline";                       // backend echoes the normalized id
      return jsonRes(200, { ok: true, workflow: wf });
    }
    if (p === "/api/active-workflow" && opts && opts.method === "PUT") {
      return jsonRes(200, { ok: true, active_workflow_id: "my-pipeline" });
    }
    if (p === "/api/active-workflow" && (!opts || !opts.method)) {
      return jsonRes(200, { active_workflow_id: "my-pipeline", workflow: { id: "my-pipeline" } });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await activateWorkflow();
  const hSave = requests.find((r) => r.path === "/api/workflows/my-pipeline" && r.opts && r.opts.method === "PUT");
  ok(hSave, "H: untitled workflow is saved under the prompted real id");
  eq(S.workflow.id, "my-pipeline", "H: S.workflow.id is replaced with the persisted id after save");
  const hAct = requests.find((r) => r.path === "/api/active-workflow" && r.opts && r.opts.method === "PUT");
  ok(hAct, "H: activation is issued after the save");
  eq(JSON.parse(hAct.opts.body).workflow_id, "my-pipeline", "H: activation uses the real persisted id");
  eq(registry["ws-activate"].textContent, "✓ Active", "H: activation succeeds after saving the untitled workflow");

  /* ── I: saveWorkflow() requires + adopts a real id (never persists "untitled") ── */
  reset();
  S.workflow = JSON.parse(JSON.stringify(WF_UNTITLED));
  global.window.prompt = () => "real-name";
  fetchImpl = async (p, opts) => {
    if (p === "/api/workflows/real-name" && opts && opts.method === "PUT") {
      const wf = JSON.parse(JSON.stringify(S.workflow));
      wf.id = "real-name";
      return jsonRes(200, { ok: true, workflow: wf });
    }
    throw new Error("unexpected fetch: " + p);
  };
  const saved = await saveWorkflow();
  const putReqs = requests.filter((r) => r.opts && r.opts.method === "PUT");
  eq(putReqs.length, 1, "I: exactly one save (PUT) request issued");
  eq(putReqs[0].path, "/api/workflows/real-name", "I: save targets the prompted real id, never \"untitled\"");
  ok(!requests.some((r) => r.path === "/api/workflows/untitled"),
     "I: the placeholder id is never sent to the backend");
  ok(saved && saved.id === "real-name", "I: saveWorkflow returns the persisted workflow");
  eq(S.workflow.id, "real-name", "I: S.workflow.id is the real persisted id after save");
  global.window.prompt = () => null;

  /* ── refreshActiveIndicator reads the active id from GET ── */
  reset();
  S.workflow = { id: "wf-a", name: "", nodes: [], edges: [], entry: [], state: {}, settings: {} };
  S.activeWorkflowId = null;
  fetchImpl = async (p) => {
    if (p === "/api/active-workflow") return jsonRes(200, { active_workflow_id: "wf-a" });
    throw new Error("unexpected fetch: " + p);
  };
  await refreshActiveIndicator();
  eq(S.activeWorkflowId, "wf-a", "refreshActiveIndicator loads the active id from GET");
  eq(registry["ws-activate"].textContent, "✓ Active", "refreshActiveIndicator updates the button");

  console.log("workspace activate tests passed:", count);
}

main().catch((err) => {
  console.error("workspace activate tests FAILED:", err);
  process.exit(1);
});

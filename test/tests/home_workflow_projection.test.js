"use strict";
/* Home ← active-workflow projection tests — run with
   `node test/tests/home_workflow_projection.test.js`.

   Loads the real scripts/web_ui/static/app.js into a DOM shim and proves Home
   is a PURE projection of the active workflow:

     A. exactly one panel per workflow node (3 agents → 3 panels, no extras)
     B. replacing the workflow removes old panels and creates the new ones
     C. two nodes using the SAME agent produce two independent panels
     D. WorkflowNode.x/y drives Home layout (relative topology preserved)
     E. WorkflowEdge is rendered exactly (no inferred connections)
     F. 7 legacy agents do NOT survive workflow activation (3 nodes → 3 panels)
     G. switching workflow A → B leaves no stale panels
     I. node-aware consoles: node id, not agent tag, is the session identity
     J. buildWorkflowWorkspace never throws with uninitialized per-node caches
        (3 nodes w/ duplicate agent → 3 panels + 2 edges, node-id identity)
     K. large/negative coords → compact normalized layout, fixed panel size
*/

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const APP_JS = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "app.js");
const src = fs.readFileSync(APP_JS, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function eq(a, b, msg) { count += 1; assert.strictEqual(a, b, msg); }
function deepEq(a, b, msg) { count += 1; assert.deepStrictEqual(a, b, msg); }

/* ── minimal DOM shim (panels, consoles, edges) ─────────────────── */
function makeEl(tag) {
  const node = {
    tagName: tag,
    children: [],
    className: "",
    textContent: "",
    title: "",
    value: "",
    dataset: {},
    style: {},
    parentNode: null,
    scrollTop: 0,
    clientHeight: 200,
    _sh: 0,
    get firstChild() { return this.children[0] || null; },
    get scrollHeight() { return this._sh || this.children.length * 20; },
    set scrollHeight(v) { this._sh = v; },
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
    setAttribute(k, v) {
      if (k === "class") this.className = v;
      if (k.startsWith("data-")) {
        const key = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        this.dataset[key] = v;
      }
      this[k] = v;
    },
    addEventListener() {},
    querySelector(sel) { return query(this, sel); },
    querySelectorAll(sel) { return queryAll(this, sel); },
    contains() { return false; },
    focus() {},
    getBoundingClientRect() { return { left: 0, top: 0 }; },
  };
  return node;
}

function matches(node, sel) {
  const m = sel.match(/^\.([\w-]+)(\[data-([\w-]+)="([^"]+)"\])?$/);
  if (!m) return false;
  const wantCls = m[1];
  const attr = m[3];
  const wantVal = m[4];
  const cls = new Set(String(node.className || "").split(/\s+/).filter(Boolean));
  if (!cls.has(wantCls)) return false;
  if (attr === undefined) return true;
  const key = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  return String(node.dataset[key] || "") === wantVal;
}

function walk(node, fn) {
  for (const c of node.children || []) {
    fn(c);
    walk(c, fn);
  }
}

function query(node, sel) {
  if (typeof sel === "string" && sel.startsWith("#")) {
    return sel === "#send-target" ? registry.sendTarget : null;
  }
  if (sel === "#workspace-grid") return registry.grid;
  let found = null;
  walk(node, (c) => { if (!found && matches(c, sel)) found = c; });
  return found;
}

function queryAll(node, sel) {
  if (sel === ".panel") {
    const out = [];
    walk(node, (c) => { if (String(c.className || "").split(/\s+/).includes("panel")) out.push(c); });
    return out;
  }
  return [];
}

const registry = {
  grid: makeEl("div"),
  sendTarget: makeEl("span"),
};

const document = {
  querySelector(sel) {
    if (sel === "#workspace-grid") return registry.grid;
    if (sel === "#send-target") return registry.sendTarget;
    if (sel.startsWith(".panel[data-")) return query(registry.grid, sel);
    return null;
  },
  querySelectorAll(sel) { return queryAll(registry.grid, sel); },
  createElement: (t) => makeEl(t),
  createElementNS: () => makeEl("g"),
  addEventListener() {},
  documentElement: {},
  body: { style: { setProperty() {} } },
};

global.window = {
  addEventListener() {},
  innerWidth: 1000,
  innerHeight: 800,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
};
global.document = document;
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

eval(src); // IIFE runs; DOMContentLoaded init is never fired

const REGISTRY = [
  { tag: "m1", name: "Matthew", agent: "matthew" },
  { tag: "m2", name: "Alex", agent: "alex" },
  { tag: "m3", name: "Sarah", agent: "sarah" },
  { tag: "m4", name: "David", agent: "david" },
  { tag: "m5", name: "Elena", agent: "elena" },
  { tag: "m6", name: "Max", agent: "max" },
  { tag: "m7", name: "Chloe", agent: "chloe" },
];

function homeNodes(wf) {
  const { Ag } = global.window.MACApp;
  Ag.homeWorkflow = wf;
  Ag.homeNodes = (wf.nodes || []).filter((n) => n.kind === "agent");
  Ag.homeEdges = wf.edges || [];
}

function panels() {
  return registry.grid.children.filter((c) => c.className.split(/\s+/).includes("panel"));
}

function panelByNode(nodeId) {
  return registry.grid.querySelector(`.panel[data-workflow-node-id="${nodeId}"]`);
}

function consoleText(nodeId) {
  const p = panelByNode(nodeId);
  return p ? p.querySelector(".p-console").children.map((c) => c.textContent) : [];
}

const WF3 = {
  id: "wf3", name: "Pipeline",
  nodes: [
    { id: "n1", agent: "matthew", kind: "agent", label: "Matthew", x: 100, y: 100, model: "" },
    { id: "n2", agent: "alex", kind: "agent", label: "Alex", x: 500, y: 100, model: "opencode/big-pickle" },
    { id: "n3", agent: "sarah", kind: "agent", label: "Sarah", x: 500, y: 400, model: "" },
  ],
  edges: [
    { source: "n1", target: "n2", condition: "" },
    { source: "n2", target: "n3", condition: "success" },
  ],
};

function main() {
  const { Ag, buildWorkspace, buildWorkflowWorkspace, nodeEvent, setActiveNode } =
    global.window.MACApp;

  // 7 legacy agents exist in the registry, but NO workflow is active yet:
  Ag.agents = REGISTRY.map((r) => Object.assign({}, r, {
    model: "", status: "idle", progress: 0, token_usage: 0, running: false, prompt: "",
  }));
  Ag.prefs.agents_visible = REGISTRY.map((r) => r.tag);   // all 7 would be visible
  Ag.homeWorkflow = null; Ag.homeNodes = []; Ag.homeEdges = [];
  Ag.nodeSessions = {}; Ag.runStatuses = {};

  // ── A. 3 workflow nodes → exactly 3 panels, nothing else ──
  homeNodes(WF3);
  buildWorkspace();
  eq(panels().length, 3, "A: Home has exactly 3 panels (one per workflow node)");
  eq(panelByNode("n1").dataset.workflowNodeId, "n1", "A: panel carries its workflow node id");
  ok(panelByNode("n2") && panelByNode("n3"), "A: all workflow nodes have panels");

  // ── D. layout comes from WorkflowNode.x/y (relative topology preserved) ──
  const p1 = parseFloat(panelByNode("n1").style.left), p2 = parseFloat(panelByNode("n2").style.left);
  const t1 = parseFloat(panelByNode("n1").style.top), t2 = parseFloat(panelByNode("n2").style.top);
  const p3 = parseFloat(panelByNode("n3").style.left), t3 = parseFloat(panelByNode("n3").style.top);
  ok(p1 < p2, "D: n1 is left of n2 (x grows)");
  eq(Math.round(p2), Math.round(p3), "D: n2 and n3 share the same x (500)");
  eq(Math.round(t1), Math.round(t2), "D: n1 and n2 share the same y (100)");
  ok(t2 < t3, "D: n3 is below n2 (y grows)");

  // ── E. edges are a direct projection of WorkflowEdge ──
  const svg = registry.grid.children.filter((c) => c.className.includes("home-edges"))[0];
  ok(svg, "E: an edge SVG layer exists");
  const lines = svg.children.filter((c) => c.className.includes("home-edge"));
  eq(lines.length, 2, "E: exactly the workflow's 2 edges are rendered");
  eq(lines[0].dataset.source, "n1", "E: edge source references the workflow node id");
  eq(lines[0].dataset.target, "n2", "E: edge target references the workflow node id");
  eq(lines[1].dataset.source, "n2", "E: edge source references the workflow node id");
  eq(lines[1].dataset.target, "n3", "E: edge target references the workflow node id");
  eq(lines[0].dataset.condition, undefined, "E: unconditional edge has no condition");
  eq(lines[1].dataset.condition, "success", "E: success edge carries its condition");
  eq(parseFloat(lines[0].x1), p1, "E: edge starts at the source node position");
  eq(parseFloat(lines[0].x2), p2, "E: edge ends at the target node position");

  // ── F. 7 legacy agents do NOT survive workflow activation ──
  // (Ag.agents still has 7; only the 3 workflow panels may exist)
  eq(Ag.agents.length, 7, "F: registry still has 7 agents");
  eq(panels().length, 3, "F: exactly 3 workflow panels — NOT 7, NOT 10");

  // ── I. node-aware console identity (duplicate agents stay separate) ──
  const WF_DUP = {
    id: "wf-dup", name: "Two Matthews",
    nodes: [
      { id: "n1", agent: "matthew", kind: "agent", label: "Matthew #1", x: 100, y: 100, model: "" },
      { id: "n2", agent: "matthew", kind: "agent", label: "Matthew #2", x: 500, y: 100, model: "" },
    ],
    edges: [{ source: "n1", target: "n2", condition: "" }],
  };
  homeNodes(WF_DUP);
  buildWorkspace();
  eq(panels().length, 2, "C: duplicate agent → 2 independent panels");
  const q1 = panelByNode("n1"), q2 = panelByNode("n2");
  ok(q1 && q2, "C: both workflow nodes have distinct panels");
  ok(q1 !== q2, "C: the two panels are different DOM nodes");
  eq(q1.dataset.workflowNodeId, "n1", "C: panel 1 identity is node id n1");
  eq(q2.dataset.workflowNodeId, "n2", "C: panel 2 identity is node id n2");

  // node n1 receives output; n2's console must stay empty
  nodeEvent("n1", { kind: "line", text: "only for n1" });
  deepEq(consoleText("n1"), ["only for n1"], "I: n1 console shows its own output");
  deepEq(consoleText("n2"), [], "I: n2 console is independent (no mixing)");
  deepEq(Ag.nodeSessions.n1.map((e) => e.text), ["only for n1"], "I: session keyed by node id");
  ok(!Ag.nodeSessions.n2, "I: n2 has no session from n1's event");

  // ── G. switching workflows removes stale panels ──
  const WF_B = {
    id: "wf-b", name: "B",
    nodes: [
      { id: "b1", agent: "matthew", kind: "agent", label: "Matthew", x: 100, y: 100, model: "" },
      { id: "b2", agent: "elena", kind: "agent", label: "Elena", x: 500, y: 100, model: "" },
    ],
    edges: [{ source: "b1", target: "b2", condition: "" }],
  };
  homeNodes(WF_B);
  buildWorkspace();
  const ids = panels().map((c) => c.dataset.workflowNodeId).sort();
  deepEq(ids, ["b1", "b2"], "G: after switching, exactly the new workflow's panels");
  ok(!panelByNode("n1") && !panelByNode("n2"), "G: old workflow panels are gone");
  // old edges are removed with the old panels
  const svgB = registry.grid.children.filter((c) => c.className.includes("home-edges"))[0];
  const linesB = svgB.children.filter((c) => c.className.includes("home-edge"));
  eq(linesB.length, 1, "G: after switching, exactly the new workflow's 1 edge");
  eq(linesB[0].dataset.source, "b1", "G: edge references the new source node id");
  eq(linesB[0].dataset.target, "b2", "G: edge references the new target node id");

  // ── setActiveNode targets a workflow node id (not an agent tag) ──
  setActiveNode("b1");
  eq(Ag.activeNodeId, "b1", "active node tracked by node id");
  ok(panelByNode("b1").classList.contains("active"), "active panel is the selected node");

  // ── B. replacement reconciliation (old removed, new created) ──
  const WF_C = {
    id: "wf-c", name: "C",
    nodes: [{ id: "c1", agent: "alex", kind: "agent", label: "Alex", x: 100, y: 100, model: "" }],
    edges: [],
  };
  homeNodes(WF_C);
  buildWorkspace();
  eq(panels().length, 1, "B: replacing the workflow leaves exactly the new panels");
  ok(panelByNode("c1"), "B: new panel created");
  ok(!panelByNode("b1") && !panelByNode("b2"), "B: previous panels removed");

  // ── H. no active workflow → empty state (never the legacy layout) ──
  Ag.homeWorkflow = null; Ag.homeNodes = []; Ag.homeEdges = [];
  buildWorkspace();
  eq(panels().length, 0, "H: no panels when no workflow is active");
  const empties = registry.grid.children.filter((c) =>
    String(c.className).split(/\s+/).includes("workspace-empty"));
  eq(empties.length, 1, "H: exactly one empty-state message");
  ok(String(empties[0].textContent).includes("No active workflow"),
     "H: message is the workflow empty state (not the legacy agent toggle)");

  // ── J. REGRESSION: no per-node session/cache → no exception ──
  // Simulate the app's fresh boot state (before any dispatch/stream): the
  // per-node caches are undefined. buildWorkflowWorkspace must still render a
  // panel per node (idle/ready) and every edge, never throw on a missing cache.
  Ag.nodeSessions = undefined;
  Ag.runStatuses = undefined;
  Ag.runEmitted = undefined;
  const WF_REG = {
    id: "wf-reg", name: "Regression",
    nodes: [
      { id: "n2", agent: "matthew", kind: "agent", label: "Matthew", x: 100, y: 100, model: "" },
      { id: "n3", agent: "alex", kind: "agent", label: "Alex", x: 500, y: 100, model: "" },
      { id: "n4", agent: "alex", kind: "agent", label: "Alex #2", x: 500, y: 400, model: "" },
    ],
    edges: [
      { source: "n4", target: "n2", condition: "" },
      { source: "n4", target: "n3", condition: "success" },
    ],
  };
  homeNodes(WF_REG);
  let threw = false;
  try { buildWorkspace(); } catch (_) { threw = true; }
  ok(!threw, "J: buildWorkflowWorkspace does not throw with uninitialized caches");
  eq(panels().length, 3, "J: 3 nodes → exactly 3 panels");
  const svgR = registry.grid.children.filter((c) => c.className.includes("home-edges"))[0];
  const linesR = svgR.children.filter((c) => c.className.includes("home-edge"));
  eq(linesR.length, 2, "J: 2 edges → exactly 2 rendered edges");
  eq(linesR[0].dataset.source, "n4", "J: edge source is a workflow node id");
  eq(linesR[0].dataset.target, "n2", "J: edge target is a workflow node id");
  eq(linesR[1].dataset.source, "n4", "J: edge source is a workflow node id");
  eq(linesR[1].dataset.target, "n3", "J: edge target is a workflow node id");
  // duplicate agent (Alex / Alex #2) → independent panels keyed by node id
  ok(panelByNode("n3") !== panelByNode("n4"), "J: Alex and Alex #2 are separate panels");
  eq(panelByNode("n3").dataset.workflowNodeId, "n3", "J: panel identity is the node id (n3)");
  eq(panelByNode("n4").dataset.workflowNodeId, "n4", "J: panel identity is the node id (n4)");
  eq(panelByNode("n2").dataset.workflowNodeId, "n2", "J: panel identity is the node id (n2)");

  // ── K. REGRESSION: large/negative coords → compact, fixed-size panels ──
  // The active workflow's raw coordinates can be large and negative (designer
  // world space). Home must normalize them and never blow the graph apart.
  const WF_NEG = {
    id: "wf-neg", name: "Negative coords",
    nodes: [
      { id: "n2", agent: "matthew", kind: "agent", label: "Matthew", x: -1740.4, y: -1740.8, model: "" },
      { id: "n3", agent: "alex", kind: "agent", label: "Alex", x: -1718.8, y: -1592.8, model: "" },
      { id: "n4", agent: "alex", kind: "agent", label: "Alex #2", x: -1942.8, y: -1652.2, model: "" },
    ],
    edges: [
      { source: "n4", target: "n2", condition: "" },
      { source: "n4", target: "n3", condition: "" },
    ],
  };
  Ag.nodeSessions = {}; Ag.runStatuses = {};
  homeNodes(WF_NEG);
  buildWorkspace();
  eq(panels().length, 3, "K: 3 nodes → exactly 3 panels");
  ok(panelByNode("n3") !== panelByNode("n4"), "K: Alex and Alex #2 are separate panels");
  eq(panelByNode("n3").dataset.workflowNodeId, "n3", "K: panel identity is the node id (n3)");
  eq(panelByNode("n4").dataset.workflowNodeId, "n4", "K: panel identity is the node id (n4)");
  const svgK = registry.grid.children.filter((c) => c.className.includes("home-edges"))[0];
  const linesK = svgK.children.filter((c) => c.className.includes("home-edge"));
  eq(linesK.length, 2, "K: 2 workflow edges → exactly 2 rendered edges");
  eq(linesK[0].dataset.source, "n4", "K: edge source is a workflow node id");
  eq(linesK[0].dataset.target, "n2", "K: edge target is a workflow node id");
  eq(linesK[1].dataset.source, "n4", "K: edge source is a workflow node id");
  eq(linesK[1].dataset.target, "n3", "K: edge target is a workflow node id");
  // panels keep the standard fixed Home card dimensions (never sized by coords)
  eq(panelByNode("n2").style.width, "280px", "K: panel width meets the readable minimum");
  eq(panelByNode("n2").style.height, "200px", "K: panel height meets the readable minimum");
  eq(panelByNode("n4").style.width, "280px", "K: duplicate-agent panel width is standard too");
  // normalized, compact layout: offsets are non-negative and the projected
  // spread is NOT blown up beyond the natural span (~224px) — scale capped at 1
  const lefts = ["n2", "n3", "n4"].map((id) => parseFloat(panelByNode(id).style.left));
  const tops = ["n2", "n3", "n4"].map((id) => parseFloat(panelByNode(id).style.top));
  const spreadX = Math.max(...lefts) - Math.min(...lefts);
  ok(lefts.every((l) => l >= 0), "K: normalized x is non-negative (no raw -1942 offsets)");
  ok(tops.every((t) => t >= 0), "K: normalized y is non-negative (no raw -1740 offsets)");
  ok(spreadX > 0 && spreadX <= 225, `K: horizontal spread is compact (${spreadX}px, not blown apart)`);

  console.log("home workflow projection tests passed:", count);
}

try {
  main();
} catch (err) {
  console.error("home workflow projection tests FAILED:", err);
  process.exit(1);
}

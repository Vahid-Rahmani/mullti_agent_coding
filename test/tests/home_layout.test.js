"use strict";
/* Home layout system tests — run with `node test/tests/home_layout.test.js`.

   Loads the real scripts/web_ui/static/app.js into a DOM shim and proves the
   independent Home layout layer (Workflow / Grid / Horizontal / Vertical /
   Compact / Custom) never mutates the workflow graph and always preserves
   node-id identity, duplicate-agent independence, and edge connectivity.

     A. Workflow layout (designer x/y, normalized/compact)
     B. Grid layout (responsive columns, topo order)
     C. Horizontal layout (left → right)
     D. Vertical layout (top → bottom)
     E. Compact layout (smaller cards + tighter spacing)
     F. Custom layout (explicit positions/sizes)
     G. Custom drag position persistence + resize persistence (localStorage)
     H. Duplicate agents remain independent + node-id identity
     I. Edge preservation (node-id source/target) in every mode
     J. Automatic edge repositioning after panel movement
     K. Workflow switching removes stale panels/edges
     L. Different workflows maintain independent layouts
     M. Layout changes never mutate WorkflowNode.x/y or WorkflowEdge
     N. Reset Layout restores the default (clears custom + zoom)
     O. Responsive grid behavior (narrow vs wide viewport)
     P. No active workflow → empty state
     S. Panel sizing policy (readable minimums, scroll-over-shrink, custom preserve)
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
    get firstChild() { return this.children[0] || null; },
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
  for (const c of node.children || []) { fn(c); walk(c, fn); }
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

/* persistent localStorage (Map-backed) for layout persistence tests */
const storage = new Map();
const localStorage = {
  getItem(k) { return storage.has(k) ? storage.get(k) : null; },
  setItem(k, v) { storage.set(k, String(v)); },
  removeItem(k) { storage.delete(k); },
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
  removeEventListener() {},
  innerWidth: 1000,
  innerHeight: 800,
  localStorage,
};
global.document = document;
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

eval(src); // IIFE runs; DOMContentLoaded init is never fired

const { Ag, buildWorkspace, setHomeLayout, setHomeZoom, resetHomeLayout,
        setCustomNode, moveNode, resizeNode, redrawHomeEdges, computeLayout,
        currentHomeLayout, workflowOrder } = global.window.MACApp;

const REGISTRY = [
  { tag: "m1", name: "Matthew", agent: "matthew" },
  { tag: "m2", name: "Alex", agent: "alex" },
  { tag: "m3", name: "Sarah", agent: "sarah" },
  { tag: "m4", name: "David", agent: "david" },
  { tag: "m5", name: "Elena", agent: "elena" },
  { tag: "m6", name: "Max", agent: "max" },
  { tag: "m7", name: "Chloe", agent: "chloe" },
];

// 3 nodes (Matthew, Alex, Alex #2), 2 edges (n4 → n2, n4 → n3)
const WF = {
  id: "wf-layout", name: "Layout",
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

function setActiveWorkflow(wf) {
  Ag.homeWorkflow = wf;
  Ag.homeNodes = (wf.nodes || []).filter((n) => n.kind === "agent");
  Ag.homeEdges = wf.edges || [];
}

function panels() {
  return registry.grid.children.filter((c) => String(c.className || "").split(/\s+/).includes("panel"));
}
function panelByNode(nodeId) {
  return registry.grid.querySelector(`.panel[data-workflow-node-id="${nodeId}"]`);
}
function edgeLines() {
  const svg = registry.grid.children.filter((c) => String(c.className).includes("home-edges"))[0];
  return svg ? svg.children.filter((c) => String(c.className).includes("home-edge")) : [];
}
function graphSnapshot() {
  return JSON.stringify(Ag.homeNodes.map((n) => [n.id, n.x, n.y]).concat(
    (Ag.homeEdges || []).map((e) => [e.source, e.target, e.condition])));
}

function main() {
  Ag.agents = REGISTRY.map((r) => Object.assign({}, r, {
    model: "", status: "idle", progress: 0, token_usage: 0, running: false, prompt: "",
  }));
  Ag.nodeSessions = {}; Ag.runStatuses = {};
  Ag.homeMode = "workflow"; Ag.homeZoom = 1; Ag.homeLayouts = {};

  /* ── A. Workflow layout (default): 3 panels + 2 edges, node-id identity ── */
  setActiveWorkflow(WF);
  buildWorkspace();
  const before = graphSnapshot();
  eq(panels().length, 3, "A: workflow layout → 3 panels");
  eq(edgeLines().length, 2, "A: workflow layout → 2 edges");
  ok(panelByNode("n2") && panelByNode("n3") && panelByNode("n4"), "A: every node has a panel");
  eq(panelByNode("n4").dataset.workflowNodeId, "n4", "A: panel identity is node id");

  /* ── H. duplicate agents independent in workflow mode ── */
  ok(panelByNode("n3") !== panelByNode("n4"), "H: Alex and Alex #2 are separate panels");

  /* ── I. edge preservation (node-id source/target) ── */
  const lines = edgeLines();
  eq(lines[0].dataset.source, "n4", "I: edge source is node id");
  eq(lines[0].dataset.target, "n2", "I: edge target is node id");
  eq(lines[1].dataset.source, "n4", "I: edge source is node id");
  eq(lines[1].dataset.target, "n3", "I: edge target is node id");

  /* ── B. Grid layout: responsive columns, topo order ── */
  setHomeLayout("grid");
  eq(panels().length, 3, "B: grid → 3 panels");
  eq(edgeLines().length, 2, "B: grid → 2 edges preserved");
  eq(edgeLines()[0].dataset.source, "n4", "B: grid edge source is node id");
  // wide viewport → all three fit on one row (same top)
  const gridTops = ["n2", "n3", "n4"].map((id) => Math.round(parseFloat(panelByNode(id).style.top)));
  eq(new Set(gridTops).size, 1, "B: wide viewport → single grid row");

  /* ── C. Horizontal layout: left → right (source n4 first) ── */
  deepEq(workflowOrder(WF.nodes, WF.edges), ["n4", "n2", "n3"], "C: topo order puts the entry node (n4) first");
  setHomeLayout("horizontal");
  const cx = (id) => parseFloat(panelByNode(id).style.left);
  const cy = (id) => parseFloat(panelByNode(id).style.top);
  ok(cx("n4") < cx("n2") && cx("n2") < cx("n3"), "C: horizontal → x increases left to right (n4, n2, n3)");
  eq(new Set(["n2", "n3", "n4"].map((id) => Math.round(cy(id)))).size, 1, "C: horizontal → all on one row");
  eq(edgeLines().length, 2, "C: horizontal → 2 edges preserved");

  /* ── D. Vertical layout: top → bottom (source n4 first) ── */
  setHomeLayout("vertical");
  const vy = (id) => parseFloat(panelByNode(id).style.top);
  const vx = (id) => parseFloat(panelByNode(id).style.left);
  ok(vy("n4") < vy("n2") && vy("n2") < vy("n3"), "D: vertical → y increases top to bottom (n4, n2, n3)");
  eq(new Set(["n2", "n3", "n4"].map((id) => Math.round(vx(id)))).size, 1, "D: vertical → all in one column");
  eq(edgeLines().length, 2, "D: vertical → 2 edges preserved");

  /* ── E. Compact layout: smaller cards ── */
  setHomeLayout("compact");
  eq(panelByNode("n2").style.width, "160px", "E: compact card width");
  eq(panelByNode("n2").style.height, "96px", "E: compact card height");
  eq(panels().length, 3, "E: compact → 3 panels");
  eq(edgeLines().length, 2, "E: compact → 2 edges preserved");

  /* ── F. Custom layout: explicit positions/sizes ── */
  setHomeLayout("custom");
  setCustomNode("n4", { x: 80, y: 120, w: 200, h: 150 });
  eq(panelByNode("n4").style.left, "80px", "F: custom position x");
  eq(panelByNode("n4").style.top, "120px", "F: custom position y");
  eq(panelByNode("n4").style.width, "200px", "F: custom size w");
  eq(panelByNode("n4").style.height, "150px", "F: custom size h");
  eq(edgeLines().length, 2, "F: custom → 2 edges preserved");

  /* ── G. custom position + resize persistence (localStorage round-trip) ── */
  // simulate a full reload: reset in-memory layouts, then loadHomeLayouts()
  const persistedRaw = storage.get("zova-home-layouts");
  ok(persistedRaw, "G: custom layout persisted to localStorage");
  Ag.homeLayouts = {};
  global.window.MACApp.Ag.homeLayouts = {};
  // re-read from storage by invoking the loader via the exported closure path:
  // (loadHomeLayouts is not exported, so emulate it by parsing the stored JSON)
  Ag.homeLayouts = JSON.parse(persistedRaw);
  Ag.homeMode = "custom";
  buildWorkspace();
  eq(panelByNode("n4").style.left, "80px", "G: custom position persisted after reload");
  eq(panelByNode("n4").style.width, "200px", "G: custom size persisted after reload");

  /* ── J. automatic edge repositioning after panel movement ── */
  setHomeLayout("custom");
  moveNode("n4", 300, 320);
  const line0 = edgeLines()[0]; // n4 → n2
  eq(line0.dataset.source, "n4", "J: moved edge still references node id n4");
  eq(parseFloat(line0.x1), 300, "J: edge start follows the moved panel x");
  eq(parseFloat(line0.y1), 320, "J: edge start follows the moved panel y");
  // resize also re-anchors edges (resize does not move the center here); the
  // interactive resize floor (280×180) clamps a too-small width up.
  resizeNode("n4", 260, 180);
  eq(panelByNode("n4").style.width, "280px", "J: resize clamps to the readable minimum width");
  eq(panelByNode("n4").style.height, "180px", "J: resize keeps the minimum height");

  /* ── M. layout changes never mutate the workflow graph ── */
  setHomeLayout("grid");
  setHomeLayout("custom");
  setHomeLayout("workflow");
  eq(graphSnapshot(), before, "M: workflow x/y + edges unchanged across layout changes");

  /* ── K. workflow switching removes stale panels/edges ── */
  const WF2 = {
    id: "wf-two", name: "Two",
    nodes: [
      { id: "b1", agent: "matthew", kind: "agent", label: "Matthew", x: 0, y: 0, model: "" },
      { id: "b2", agent: "elena", kind: "agent", label: "Elena", x: 100, y: 0, model: "" },
    ],
    edges: [{ source: "b1", target: "b2", condition: "" }],
  };
  Ag.homeMode = "workflow";
  setActiveWorkflow(WF2);
  buildWorkspace();
  const ids = panels().map((c) => c.dataset.workflowNodeId).sort();
  deepEq(ids, ["b1", "b2"], "K: switching workflow → exactly the new panels");
  ok(!panelByNode("n2") && !panelByNode("n4"), "K: stale panels removed");
  eq(edgeLines().length, 1, "K: stale edges removed → 1 edge");
  eq(edgeLines()[0].dataset.source, "b1", "K: new edge references new node id");

  /* ── L. different workflows maintain independent layouts ── */
  setActiveWorkflow(WF);        // back to wf-layout
  setHomeLayout("custom");
  setCustomNode("n4", { x: 55, y: 66, w: 190, h: 140 });
  setActiveWorkflow(WF2);       // wf-two has no custom layout yet
  setHomeLayout("custom");
  eq(panelByNode("b1").style.width, "280px", "L: wf-two uses default custom size (no saved layout)");
  setActiveWorkflow(WF);        // wf-layout's custom layout must still be intact
  setHomeLayout("custom");
  eq(panelByNode("n4").style.left, "55px", "L: wf-layout custom position retained independently");
  eq(panelByNode("n4").style.width, "190px", "L: wf-layout custom size retained independently");

  /* ── N. Reset Layout restores default (clears custom + zoom) ── */
  setHomeLayout("custom");
  setHomeZoom(1.3);
  setCustomNode("n4", { x: 500, y: 400, w: 300, h: 200 });
  resetHomeLayout();
  eq(currentHomeLayout().zoom, 1, "N: reset restores zoom to 100%");
  eq(panelByNode("n4").style.width, "280px", "N: reset restores default panel size");
  ok(parseFloat(panelByNode("n4").style.left) < 400, "N: reset returns panel to the default (workflow) position");

  /* ── O. responsive grid behavior (narrow viewport → more rows) ── */
  setActiveWorkflow(WF);
  setHomeLayout("grid");
  global.window.innerWidth = 360;   // narrow → 1 column
  buildWorkspace();
  const narrowLefts = ["n2", "n3", "n4"].map((id) => Math.round(parseFloat(panelByNode(id).style.left)));
  eq(new Set(narrowLefts).size, 1, "O: narrow viewport → single column (same x)");
  const narrowTops = ["n2", "n3", "n4"].map((id) => Math.round(parseFloat(panelByNode(id).style.top)));
  eq(new Set(narrowTops).size, 3, "O: narrow viewport → 3 rows (distinct y)");
  global.window.innerWidth = 1000;  // wide → 1 row
  buildWorkspace();
  const wideTops = ["n2", "n3", "n4"].map((id) => Math.round(parseFloat(panelByNode(id).style.top)));
  eq(new Set(wideTops).size, 1, "O: wide viewport → single row");

  /* ── S. panel sizing policy (larger readable panels + scrolling) ── */
  const WIDE6 = {
    id: "wf-wide", name: "Wide",
    nodes: ["n1", "n2", "n3", "n4", "n5", "n6"].map((id, i) => ({
      id, agent: ["matthew", "alex", "sarah", "david", "elena", "max"][i],
      kind: "agent", label: "A" + i, x: i * 100, y: 0, model: "",
    })),
    edges: ["n1", "n2", "n3", "n4", "n5"].map((s, i) =>
      ({ source: s, target: "n" + (i + 2), condition: "" })),
  };
  setActiveWorkflow(WF);
  global.window.innerWidth = 1000;

  // S1. Grid panels meet the readable minimum dimensions
  setHomeLayout("grid");
  ["n2", "n3", "n4"].forEach((id) => {
    ok(parseFloat(panelByNode(id).style.width) >= 280, "S1: grid panel width >= readable min");
    ok(parseFloat(panelByNode(id).style.height) >= 200, "S1: grid panel height >= readable min");
  });

  // S2. Vertical panels use most of the available Home width
  setHomeLayout("vertical");
  ok(parseFloat(panelByNode("n2").style.width) >= 700, "S2: vertical panel uses most of the Home width");

  // S3. Horizontal panels keep a readable width (never shrink)
  setHomeLayout("horizontal");
  eq(panelByNode("n2").style.width, "360px", "S3: horizontal panel uses the preferred width");
  ["n2", "n3", "n4"].forEach((id) =>
    ok(parseFloat(panelByNode(id).style.width) >= 280, "S3: horizontal panel width >= readable min"));

  // S4. Horizontal overflow → scroll, panels never shrink to fit
  setActiveWorkflow(WIDE6);
  setHomeLayout("horizontal");
  const lastX = parseFloat(panelByNode("n6").style.left);
  const lastW = parseFloat(panelByNode("n6").style.width);
  ok(lastX + lastW / 2 > 952, "S4: horizontal row overflows the viewport (scroll, not shrink)");
  eq(panelByNode("n6").style.width, "360px", "S4: no panel shrank to fit the viewport");

  // S5. Compact is the only mode with significantly smaller panels
  setActiveWorkflow(WF);
  setHomeLayout("compact");
  eq(panelByNode("n2").style.width, "160px", "S5: compact uses small panels");
  ok(parseFloat(panelByNode("n2").style.width) < 280, "S5: compact width is below the standard minimum");

  // S6. Custom panel sizes are preserved exactly (no auto-resize)
  setHomeLayout("custom");
  setCustomNode("n4", { x: 120, y: 140, w: 210, h: 170 });
  eq(panelByNode("n4").style.width, "210px", "S6: custom width preserved exactly");
  eq(panelByNode("n4").style.height, "170px", "S6: custom height preserved exactly");

  // S7. Edges stay connected to node centers after a resize
  resizeNode("n4", 320, 240);
  const lineResized = edgeLines()[0];
  eq(lineResized.dataset.source, "n4", "S7: edge still references node id after resize");
  eq(parseFloat(lineResized.x1), parseFloat(panelByNode("n4").style.left),
     "S7: edge start follows the panel center after resize");

  /* ── S8. No snap-back: interactive + programmatic custom sizes beyond the
         legacy 480×400 render cap round-trip a rebuild unchanged ── */
  setHomeLayout("custom");
  resizeNode("n4", 520, 200);   // 520px exceeds the old 480px render cap
  eq(panelByNode("n4").style.width, "520px", "S8: interactive resize accepts an in-workspace width");
  buildWorkspace();             // simulate the 3s poll / session-reload rebuild
  eq(panelByNode("n4").style.width, "520px", "S8: rebuild preserves the width (no snap-back)");
  setCustomNode("n4", { w: 640, h: 200 });   // programmatic path shares the ceiling
  eq(panelByNode("n4").style.width, "640px", "S8: programmatic width above 480 preserved");

  /* ── P. no active workflow → empty state ── */
  Ag.homeWorkflow = null; Ag.homeNodes = []; Ag.homeEdges = [];
  buildWorkspace();
  eq(panels().length, 0, "P: no panels without an active workflow");
  const empties = registry.grid.children.filter((c) =>
    String(c.className).split(/\s+/).includes("workspace-empty"));
  eq(empties.length, 1, "P: empty-state message shown");
  ok(String(empties[0].textContent).includes("No active workflow"), "P: empty-state text");

  console.log("home layout tests passed:", count);
}

try {
  main();
} catch (err) {
  console.error("home layout tests FAILED:", err);
  process.exit(1);
}

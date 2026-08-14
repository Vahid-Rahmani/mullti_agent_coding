"use strict";
/* Home agent panel drag/resize tests — run with `node test/tests/home_drag_resize.test.js`.

   Loads the real scripts/web_ui/static/app.js into a DOM shim and proves every
   agent panel is draggable + resizable while the workflow graph stays untouched:

     D1. A panel is draggable and only that node moves.
     D2. Dragging does not mutate WorkflowNode.x/y or WorkflowEdge.
     D3. Dragging switches the layout mode to Custom.
     D4. A panel is resizable and respects the readable minimum width/height.
     D5. Resizing switches the layout mode to Custom and never mutates the graph.
     D6. Custom positions persist (localStorage keyed by workflow id).
     D7. Custom sizes persist.
     D8. Duplicate agents remain independent panels (n3 vs n4).
     D9. Workflow switching loads the correct (independent) Home layout.
    D10. Old panels are removed when switching workflows.
    D11. Edges stay connected to node centers after dragging.
    D12. Edges stay connected after resizing.
    D13. Reset Layout discards custom + returns to the selected default mode.
    D14. Dragging past the top/left keeps the panel on the workspace.
    D15. No active workflow → empty state.
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

/* ── DOM shim (panels, consoles, edges) with attribute-aware queries ── */
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
    clientWidth: 1000,
    clientHeight: 600,
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

function hasClass(node, cls) {
  return String(node.className || "").split(/\s+/).includes(cls);
}

function matches(node, sel) {
  const m = sel.match(/^\.([\w-]+)(\[data-([\w-]+)(="([^"]+)")?\])?$/);
  if (!m) return false;
  const wantCls = m[1];
  const attr = m[3];
  const wantVal = m[5];
  if (!hasClass(node, wantCls)) return false;
  if (attr === undefined) return true;
  const key = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  const have = node.dataset[key];
  if (wantVal === undefined) return have !== undefined && have !== "";
  return String(have || "") === wantVal;
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
  const out = [];
  walk(node, (c) => { if (matches(c, sel)) out.push(c); });
  return out;
}

const registry = {
  grid: makeEl("div"),
  sendTarget: makeEl("span"),
};

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
    return query(registry.grid, sel);
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

eval(src);

const { Ag, buildWorkspace, setHomeLayout, resetHomeLayout, setCustomNode,
        moveNode, resizeNode, currentHomeLayout, switchToCustom } = global.window.MACApp;

const REGISTRY = [
  { tag: "m1", name: "Matthew", agent: "matthew" },
  { tag: "m2", name: "Alex", agent: "alex" },
  { tag: "m3", name: "Sarah", agent: "sarah" },
];

const WF = {
  id: "wf-drag", name: "Drag",
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
  return registry.grid.children.filter((c) => hasClass(c, "panel"));
}
function panelByNode(nodeId) {
  return registry.grid.querySelector(`.panel[data-workflow-node-id="${nodeId}"]`);
}
function edgeLines() {
  const svg = registry.grid.children.filter((c) => String(c.className).includes("home-edges"))[0];
  return svg ? svg.children.filter((c) => hasClass(c, "home-edge")) : [];
}
function graphSnapshot() {
  return JSON.stringify(Ag.homeNodes.map((n) => [n.id, n.x, n.y]).concat(
    (Ag.homeEdges || []).map((e) => [e.source, e.target, e.condition])));
}
function pos(id) {
  const c = panelByNode(id);
  return { x: parseFloat(c.style.left), y: parseFloat(c.style.top) };
}

function main() {
  Ag.agents = REGISTRY.map((r) => Object.assign({}, r, {
    model: "", status: "idle", progress: 0, token_usage: 0, running: false, prompt: "",
  }));
  Ag.nodeSessions = {}; Ag.runStatuses = {};
  Ag.homeMode = "workflow"; Ag.homeZoom = 1; Ag.homeLayouts = {};
  storage.clear();

  /* ── D1/D2. draggable, only that node moves, graph untouched ── */
  setActiveWorkflow(WF);
  setHomeLayout("grid");
  buildWorkspace();
  const before = graphSnapshot();
  const n2Before = pos("n2"), n3Before = pos("n3");
  moveNode("n4", 400, 300);
  eq(pos("n4").x, 400, "D1: dragging sets the panel x");
  eq(pos("n4").y, 300, "D1: dragging sets the panel y");
  deepEq(pos("n2"), n2Before, "D1: dragging does not move n2");
  deepEq(pos("n3"), n3Before, "D1: dragging does not move n3");
  eq(graphSnapshot(), before, "D2: dragging never mutates WorkflowNode.x/y or edges");

  /* ── D3. dragging switches the layout mode to Custom ── */
  eq(currentHomeLayout().mode, "custom", "D3: dragging promotes the layout to Custom");

  /* ── D11. edges follow the dragged panel's center ── */
  const e0 = edgeLines()[0];  // n4 → n2
  eq(e0.dataset.source, "n4", "D11: edge still references node id after drag");
  eq(parseFloat(e0.x1), 400, "D11: edge start follows the moved panel center x");
  eq(parseFloat(e0.y1), 300, "D11: edge start follows the moved panel center y");

  /* ── D6/D7. custom position + size persist (localStorage, keyed by wf) ── */
  resizeNode("n4", 420, 300);
  let persisted = JSON.parse(storage.get("zova-home-layouts"));
  ok(persisted && persisted[WF.id], "D6: layout persisted under the workflow id");
  eq(persisted[WF.id].custom.n4.x, 400, "D6: custom position x persisted");
  eq(persisted[WF.id].custom.n4.y, 300, "D6: custom position y persisted");
  eq(persisted[WF.id].custom.n4.w, 420, "D7: custom size width persisted");
  eq(persisted[WF.id].custom.n4.h, 300, "D7: custom size height persisted");

  /* ── D8. duplicate agents independent (n3 vs n4) ── */
  ok(panelByNode("n3") !== panelByNode("n4"), "D8: Alex and Alex #2 are separate panels");
  moveNode("n3", 500, 220);
  eq(pos("n4").x, 400, "D8: moving n3 leaves n4 in place (independent)");

  /* ── D12. edges follow the panel center after resize ── */
  const eR = edgeLines()[0];
  eq(eR.dataset.source, "n4", "D12: edge still references node id after resize");
  eq(parseFloat(eR.x1), pos("n4").x, "D12: edge start matches the panel center after resize");
  eq(parseFloat(eR.y1), pos("n4").y, "D12: edge start matches the panel center after resize");

  /* ── D4/D5. resizable + min floor + graph untouched (fresh mode) ── */
  setHomeLayout("grid");   // explicit non-custom mode again
  const before2 = graphSnapshot();
  resizeNode("n4", 100, 100);
  eq(panelByNode("n4").style.width, "280px", "D4: resize clamps to the min width");
  eq(panelByNode("n4").style.height, "180px", "D4: resize clamps to the min height");
  eq(currentHomeLayout().mode, "custom", "D5: resizing promotes the layout to Custom");
  eq(graphSnapshot(), before2, "D5: resizing never mutates the workflow graph");
  resizeNode("n4", 420, 300);
  eq(panelByNode("n4").style.width, "420px", "D4: resize accepts a readable in-range width");
  eq(panelByNode("n4").style.height, "300px", "D4: resize accepts a readable in-range height");

  /* ── D13. Reset Layout discards custom + returns to selected default ── */
  setHomeLayout("grid");        // explicit default = grid
  moveNode("n4", 620, 260);     // → Custom
  eq(currentHomeLayout().mode, "custom", "D13: drag promoted to Custom");
  resetHomeLayout();
  eq(currentHomeLayout().mode, "grid", "D13: reset returns to the selected default mode (grid)");
  eq(currentHomeLayout().zoom, 1, "D13: reset restores zoom to 100%");
  const gridLefts = ["n2", "n3", "n4"].map((id) => Math.round(pos(id).x));
  eq(new Set(gridLefts).size, 3, "D13: reset recalculates the default grid layout (3 columns)");

  /* ── D14. dragging past the top/left keeps the panel on the workspace ── */
  setHomeLayout("custom");
  buildWorkspace();
  moveNode("n4", -1000, -1000);
  const p = pos("n4");
  const w = parseFloat(panelByNode("n4").style.width);
  const h = parseFloat(panelByNode("n4").style.height);
  ok(p.x >= w / 2 - 0.001 && p.y >= h / 2 - 0.001, "D14: panel can't be dragged off the top/left");

  /* ── D9/D10. workflow switching loads the correct independent layout ── */
  const WF2 = {
    id: "wf-drag2", name: "Drag2",
    nodes: [
      { id: "c1", agent: "matthew", kind: "agent", label: "Matthew", x: 0, y: 0, model: "" },
      { id: "c2", agent: "sarah", kind: "agent", label: "Sarah", x: 100, y: 0, model: "" },
    ],
    edges: [{ source: "c1", target: "c2", condition: "" }],
  };
  setActiveWorkflow(WF2);
  setHomeLayout("workflow");
  buildWorkspace();
  const wf2ids = panels().map((c) => c.dataset.workflowNodeId).sort();
  deepEq(wf2ids, ["c1", "c2"], "D10: switching workflow → exactly the new panels");
  ok(!panelByNode("n2") && !panelByNode("n4"), "D10: stale panels removed");
  setActiveWorkflow(WF);        // back to WF → its own (independent) layout
  setHomeLayout("custom");
  eq(panels().length, 3, "D9: switching back restores WF's 3 panels");
  ok(panelByNode("n4"), "D9: WF's nodes render independently of WF2");

  /* ── D15. no active workflow → empty state ── */
  Ag.homeWorkflow = null; Ag.homeNodes = []; Ag.homeEdges = [];
  buildWorkspace();
  eq(panels().length, 0, "D15: no panels without an active workflow");
  const empties = registry.grid.children.filter((c) => hasClass(c, "workspace-empty"));
  eq(empties.length, 1, "D15: empty-state message shown");

  console.log("home drag/resize tests passed:", count);
}

try {
  main();
} catch (err) {
  console.error("home drag/resize tests FAILED:", err);
  process.exit(1);
}

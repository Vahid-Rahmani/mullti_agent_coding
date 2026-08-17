"use strict";
/* Home agent-window 8-direction resize tests — run with `node test/tests/home_resize_edges.test.js`.

   Proves every agent window is resizable from all eight edges/corners with
   normal desktop-window semantics (the edge opposite the handle stays fixed),
   respecting the readable minimum and the workspace ceiling:

     R1. Every panel gets 8 resize handles (n/s/e/w/ne/nw/se/sw) with data-dir.
     R2. East edge: grows right, left edge fixed.
     R3. West edge: grows left, right edge fixed.
     R4. South edge: grows down, top edge fixed.
     R5. North edge: grows up, bottom edge fixed.
     R6. Corners move the two adjacent edges; the opposite corner stays fixed.
     R7. Resize clamps to the readable minimum and the workspace ceiling.
     R8. Directional resize persists to the per-workflow custom layout.
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
function near(a, b, msg) { count += 1; assert.ok(Math.abs(a - b) < 0.001, msg + ` (${a} ≈ ${b})`); }

/* ── DOM shim (same shape as home_drag_resize.test.js) ─────────────── */
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
  if (!hasClass(node, m[1])) return false;
  const attr = m[3];
  if (attr === undefined) return true;
  const key = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  const have = node.dataset[key];
  if (m[5] === undefined) return have !== undefined && have !== "";
  return String(have || "") === m[5];
}
function walk(node, fn) { for (const c of node.children || []) { fn(c); walk(c, fn); } }
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

const registry = { grid: makeEl("div"), sendTarget: makeEl("span") };
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

const { Ag, buildWorkspace, setHomeLayout, moveNode, resizeNode,
        resizeNodeDelta, RESIZE_DIRS } = global.window.MACApp;

const REGISTRY = [
  { tag: "m1", name: "Matthew", agent: "matthew" },
];
const WF = {
  id: "wf-resize", name: "Resize",
  nodes: [{ id: "n1", agent: "matthew", kind: "agent", label: "Matthew", x: 0, y: 0, model: "" }],
  edges: [],
};

function setActiveWorkflow(wf) {
  Ag.homeWorkflow = wf;
  Ag.homeNodes = (wf.nodes || []).filter((n) => n.kind === "agent");
  Ag.homeEdges = wf.edges || [];
}
function panelByNode(id) {
  return registry.grid.querySelector(`.panel[data-workflow-node-id="${id}"]`);
}
function geo(id) {
  const c = panelByNode(id);
  return { x: parseFloat(c.style.left), y: parseFloat(c.style.top),
           w: parseFloat(c.style.width), h: parseFloat(c.style.height) };
}

function main() {
  Ag.agents = REGISTRY.map((r) => Object.assign({}, r, {
    model: "", status: "idle", progress: 0, token_usage: 0, running: false, prompt: "",
  }));
  Ag.nodeSessions = {}; Ag.runStatuses = {};
  Ag.homeMode = "custom"; Ag.homeZoom = 1; Ag.homeLayouts = {};
  storage.clear();

  setActiveWorkflow(WF);
  setHomeLayout("custom");
  buildWorkspace();

  /* R1 — every panel carries 8 directional handles */
  const handles = panelByNode("n1").querySelectorAll(".panel-resize");
  eq(handles.length, 8, "R1: 8 resize handles per panel");
  deepEq(handles.map((h) => h.dataset.dir).sort(), RESIZE_DIRS.slice().sort(),
         "R1: handles carry every direction exactly once");

  // Deterministic start geometry: center (400,300), size 300×200 — plenty of
  // room in every direction so leading-edge clamping never distorts the test.
  moveNode("n1", 400, 300);
  resizeNode("n1", 300, 200);
  let g = geo("n1");
  near(g.x, 400, "setup: center x"); near(g.y, 300, "setup: center y");
  near(g.w, 300, "setup: width"); near(g.h, 200, "setup: height");

  const leftEdge = () => g.x - g.w / 2, rightEdge = () => g.x + g.w / 2;
  const topEdge = () => g.y - g.h / 2, bottomEdge = () => g.y + g.h / 2;
  const resetGeo = () => { moveNode("n1", 400, 300); resizeNode("n1", 300, 200); g = geo("n1"); };

  /* R2 — east: width grows right, left edge fixed */
  resetGeo();
  let beforeLeft = leftEdge();
  resizeNodeDelta("n1", "e", 40, 0);
  g = geo("n1");
  near(g.w, 340, "R2: east grows width"); near(leftEdge(), beforeLeft, "R2: left edge fixed");
  near(g.h, 200, "R2: height unchanged");

  /* R3 — west: width grows left, right edge fixed */
  resetGeo();
  let beforeRight = rightEdge();
  resizeNodeDelta("n1", "w", -40, 0);
  g = geo("n1");
  near(g.w, 340, "R3: west grows width"); near(rightEdge(), beforeRight, "R3: right edge fixed");

  /* R4 — south: height grows down, top edge fixed */
  resetGeo();
  let beforeTop = topEdge();
  resizeNodeDelta("n1", "s", 0, 60);
  g = geo("n1");
  near(g.h, 260, "R4: south grows height"); near(topEdge(), beforeTop, "R4: top edge fixed");

  /* R5 — north: height grows up, bottom edge fixed */
  resetGeo();
  let beforeBottom = bottomEdge();
  resizeNodeDelta("n1", "n", 0, -60);
  g = geo("n1");
  near(g.h, 260, "R5: north grows height"); near(bottomEdge(), beforeBottom, "R5: bottom edge fixed");

  /* R6 — corners move two adjacent edges; opposite corner stays fixed */
  resetGeo();
  const tl = { x: leftEdge(), y: topEdge() };
  resizeNodeDelta("n1", "se", 40, 60);   // bottom-right corner moves out
  g = geo("n1");
  near(leftEdge(), tl.x, "R6: se keeps the top-left corner fixed (x)");
  near(topEdge(), tl.y, "R6: se keeps the top-left corner fixed (y)");
  near(g.w, 340, "R6: se grows width"); near(g.h, 260, "R6: se grows height");

  resetGeo();
  const br = { x: rightEdge(), y: bottomEdge() };
  resizeNodeDelta("n1", "nw", -40, -60);  // top-left corner moves out
  g = geo("n1");
  near(rightEdge(), br.x, "R6: nw keeps the bottom-right corner fixed (x)");
  near(bottomEdge(), br.y, "R6: nw keeps the bottom-right corner fixed (y)");
  near(g.w, 340, "R6: nw grows width"); near(g.h, 260, "R6: nw grows height");

  /* R7 — min/max clamping */
  resizeNodeDelta("n1", "e", -100000, 0);
  g = geo("n1");
  near(g.w, 280, "R7: width clamped to the readable minimum");
  resizeNodeDelta("n1", "e", 100000, 0);
  g = geo("n1");
  ok(g.w <= 952, "R7: width clamped to the workspace ceiling");
  resizeNodeDelta("n1", "s", 0, 100000);
  g = geo("n1");
  ok(g.h <= 552, "R7: height clamped to the workspace ceiling");

  /* R8 — directional resize persists to the per-workflow custom layout */
  resizeNodeDelta("n1", "se", 60, 40);
  g = geo("n1");
  const persisted = JSON.parse(storage.get("zova-home-layouts"));
  const custom = persisted[WF.id].custom.n1;
  near(custom.w, g.w, "R8: persisted custom width");
  near(custom.h, g.h, "R8: persisted custom height");
  near(custom.x, g.x, "R8: persisted custom center x");
  near(custom.y, g.y, "R8: persisted custom center y");

  console.log("home resize-edges tests passed:", count);
}

try {
  main();
} catch (err) {
  console.error("home resize-edges tests FAILED:", err);
  process.exit(1);
}

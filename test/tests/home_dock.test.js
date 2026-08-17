"use strict";
/* Home bottom-dock + stream-lifecycle tests — run with `node test/tests/home_dock.test.js`.

   Proves the Status/Tasks/Execution/Logs dock minimizes to a compact bar and
   expands back (reflowing agent windows without losing their manual layout),
   and that the SSE stream re-opens idempotently across page restores:

     K1. Minimizing collapses the dock to a compact bar and records the state.
     K2. Expanding restores the previous height and clears the minimized state.
     K3. The minimized state persists (localStorage) across reloads.
     K4. Dock toggle reflows windows WITHOUT destroying custom positions/sizes.
     K5. Re-opening the stream closes the previous connection (no duplicates).
*/

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const APP_JS = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "app.js");
const src = fs.readFileSync(APP_JS, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function eq(a, b, msg) { count += 1; assert.strictEqual(a, b, msg); }

/* ── DOM shim with a real-ish body (classList + CSS-variable map) ─── */
function makeEl(tag) {
  const node = {
    tagName: tag, children: [], className: "", textContent: "", title: "",
    value: "", dataset: {}, style: {}, parentNode: null, scrollTop: 0,
    clientWidth: 1000, clientHeight: 600,
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
function hasClass(node, cls) { return String(node.className || "").split(/\s+/).includes(cls); }
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
    if (sel === "#send-target") return registry.sendTarget;
    return null;
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
const body = {
  classList: {
    _s: new Set(),
    add(...c) { c.forEach((x) => this._s.add(x)); },
    remove(...c) { c.forEach((x) => this._s.delete(x)); },
    contains(c) { return this._s.has(c); },
  },
  style: {
    _map: {},
    setProperty(k, v) { this._map[k] = String(v); },
    getPropertyValue(k) { return this._map[k] || ""; },
  },
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
  body,
  hidden: false,
};
global.window = {
  addEventListener() {}, removeEventListener() {},
  innerWidth: 1000, innerHeight: 800, localStorage,
};
global.document = document;
global.getComputedStyle = (el) => ({
  getPropertyValue: (k) => (el && el.style && el.style.getPropertyValue ? el.style.getPropertyValue(k) : ""),
});

/* Fake EventSource to prove openStream is idempotent (BFCache restores). */
function FakeEventSource(url) {
  this.url = url; this.closed = false;
  FakeEventSource.instances.push(this);
}
FakeEventSource.prototype.addEventListener = function () {};
FakeEventSource.prototype.close = function () { this.closed = true; };
FakeEventSource.instances = [];
global.EventSource = FakeEventSource;

eval(src);

const { Ag, buildWorkspace, setHomeLayout, moveNode, resizeNode,
        setBottomMinimized, toggleBottomDock, openStream } = global.window.MACApp;

const REGISTRY = [{ tag: "m1", name: "Matthew", agent: "matthew" }];
const WF = {
  id: "wf-dock", name: "Dock",
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
  moveNode("n1", 400, 300);
  resizeNode("n1", 320, 220);

  /* K1 — minimize collapses the dock */
  setBottomMinimized(true);
  eq(Ag.bottomMinimized, true, "K1: minimized flag set");
  ok(body.classList.contains("bottom-minimized"), "K1: body carries the minimized class");
  eq(body.style.getPropertyValue("--bottom-h"), "34px", "K1: dock collapses to the compact bar");

  /* K3 — persisted minimized state */
  eq(localStorage.getItem("zova-bottom-minimized"), "1", "K3: minimized state persisted");

  /* K4 — toggle reflowed the windows but kept the custom layout */
  eq(panelByNode("n1").style.left, "400px", "K4: custom position preserved through minimize");
  eq(panelByNode("n1").style.width, "320px", "K4: custom size preserved through minimize");

  /* K2 — expand restores the previous height */
  toggleBottomDock();
  eq(Ag.bottomMinimized, false, "K2: minimized flag cleared");
  ok(!body.classList.contains("bottom-minimized"), "K2: minimized class removed");
  eq(body.style.getPropertyValue("--bottom-h"), "200px", "K2: dock restores the expanded height");
  eq(localStorage.getItem("zova-bottom-minimized"), "0", "K2: state persisted as expanded");

  /* K5 — re-opening the stream closes the previous connection */
  FakeEventSource.instances = [];
  openStream();
  openStream();
  eq(FakeEventSource.instances.length, 2, "K5: a new stream is created on re-open");
  eq(FakeEventSource.instances[0].closed, true, "K5: the previous stream is closed");
  eq(FakeEventSource.instances[1].closed, false, "K5: only the latest stream stays open");

  console.log("home dock tests passed:", count);
}

try {
  main();
} catch (err) {
  console.error("home dock tests FAILED:", err);
  process.exit(1);
}

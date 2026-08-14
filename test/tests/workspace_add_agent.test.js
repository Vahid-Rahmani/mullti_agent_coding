"use strict";
/* workspace add-agent + drag/drop regression test — run with
   `node test/tests/workspace_add_agent.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim (init runs;
   fetch is mocked) and proves the full Agent Library → Canvas interaction:

     A. the agent list is loaded from the existing /api/agents registry
     B. clicking an agent creates a node (existing click-to-add)
     C. the created node references the selected agent (identity, not a model)
     D. each node gets a unique id and initializes its model to Auto
     E. library items are draggable and dragstart stores the agent key only
     F. the canvas accepts dragover and becomes a drop target
     G. dropping converts client coordinates to canvas coordinates and creates
        the node at the drop point (not a fixed slot)
     H. the dropped node is selected
     I. existing pointer-based node move/connect handlers are preserved
     J. the search filter narrows the available agents
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
  const node = {
    tagName: tag,
    children: [],
    className: "",
    textContent: "",
    title: "",
    value: "",
    dataset: {},
    style: {},
    draggable: false,
    parentNode: null,
    _handlers: {},               // type -> [fn]
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
    setAttribute(k, v) { this[k] = v; },
    addEventListener(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); },
    dispatch(type, ev) { (this._handlers[type] || []).forEach((fn) => fn(ev)); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    contains() { return false; },
    focus() {},
    getBoundingClientRect() { return { left: 0, top: 0 }; },
    get firstChild() { return this.children[0] || null; },
  };
  return node;
}

const registry = {};
const document = {
  readyState: "complete",          // run init() immediately on eval
  title: "",
  querySelector(sel) {
    if (!registry[sel]) registry[sel] = makeEl("div");
    return registry[sel];
  },
  querySelectorAll() { return []; },
  createElement: (t) => makeEl(t),
  createElementNS: () => makeEl("g"),
  addEventListener() {},
};

global.window = {
  addEventListener() {},
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
};
global.document = document;

// fetch mock: agents, roles, models, workflow list + templates
global.fetch = async (url) => {
  if (url === "/api/agents") {
    return { ok: true, json: async () => ({ agents: [
      { tag: "m1", name: "Matthew", agent: "matthew", model: "opencode/deepseek-v4-flash-free" },
      { tag: "m2", name: "Alex", agent: "alex", model: "opencode/big-pickle" },
    ] }) };
  }
  if (url === "/api/settings/roles") {
    return { ok: true, json: async () => ({ roles: [], assignments: {} }) };
  }
  if (url === "/api/settings/models") {
    return { ok: true, json: async () => ({ available: [] }) };
  }
  if (url === "/api/workflows") {
    return { ok: true, json: async () => ({ workflows: [] }) };
  }
  if (url === "/api/workflows/templates") {
    return { ok: true, json: async () => ({ templates: [] }) };
  }
  return { ok: false, json: async () => ({ detail: "not found" }) };
};

eval(src); // runs the IIFE → init() → bind() + async loadMeta()

const flush = () => new Promise((r) => setTimeout(r, 0));

async function main() {
  const { S, addNode, matchingAgents, ORIGIN } = global.window.MACWorkspace;
  await flush();               // let loadMeta complete

  // ── A. agent list is available to the workspace ──
  eq(S.agents.length, 2, "A: agent list loaded from /api/agents");
  eq(S.agents[0].agent, "matthew", "A: agent key present");

  const list = registry["#ws-library-list"];
  eq(list.children.length, 2, "A: library rendered two agent items");
  const card = list.children[0];

  // ── E. library items are draggable; dragstart stores the agent key only ──
  ok(card.draggable === true, "E: library item is draggable");
  const dt = {
    _data: {}, setData(t, v) { this._data[t] = v; },
    getData(t) { return this._data[t]; }, effectAllowed: "", dropEffect: "",
  };
  card.dispatch("dragstart", { dataTransfer: dt });
  eq(dt._data["application/x-zova-agent"], "matthew",
     "E: dragstart stores the agent key under the zova type");
  ok(!("model" in dt._data) && !("key" in dt._data),
     "E: no model/credential travels in the drag payload");

  // ── B. click-to-add still works ──
  card.dispatch("click", {});
  eq(S.workflow.nodes.length, 1, "B: clicking an agent created a node");
  const n1 = S.workflow.nodes[0];
  eq(n1.agent, "matthew", "C: node references the selected agent");
  ok(n1.id && typeof n1.id === "string", "D: node has a unique id");
  eq(n1.model, "", "D: node model initializes to Auto (empty)");

  // ── F/G/H. canvas drag/drop creates a node at the drop point ──
  const canvas = registry["#ws-canvas"];
  ok((canvas._handlers.dragover || []).length === 1, "F: canvas has a dragover handler");
  ok((canvas._handlers.drop || []).length === 1, "F: canvas has a drop handler");

  let prevented = false;
  canvas.dispatch("dragover", { preventDefault() { prevented = true; }, dataTransfer: dt });
  ok(prevented, "F: dragover prevents the browser default (valid drop target)");
  ok(canvas.classList.contains("drag-over"), "F: dragover shows the drop-target state");

  // drop at client (160, 90) with the canvas at (0,0), zoom 1, translate 0:
  // world = (client - rect - pan)/zoom - ORIGIN, so the rendered layer
  // position (node.x + ORIGIN) must equal the drop point — the node appears
  // at the mouse (regression: it used to land ORIGIN*zoom px away).
  const before = S.workflow.nodes.length;
  canvas.dispatch("drop", {
    preventDefault() {},
    dataTransfer: { getData: () => "alex" },
    clientX: 160, clientY: 90,
  });
  eq(S.workflow.nodes.length, before + 1, "G: drop created a node");
  const dropped = S.workflow.nodes[S.workflow.nodes.length - 1];
  eq(dropped.agent, "alex", "G: dropped node references the dragged agent");
  eq(dropped.x, 160 - ORIGIN, "G: drop x is a world coordinate (centred near zero)");
  eq(dropped.y, 90 - ORIGIN, "G: drop y is a world coordinate (centred near zero)");
  eq(dropped.x + ORIGIN, 160, "G: rendered x equals the drop client x (visible)");
  eq(dropped.y + ORIGIN, 90, "G: rendered y equals the drop client y (visible)");
  eq(S.selected.type, "node", "H: dropped node is selected");
  eq(S.selected.id, dropped.id, "H: selected id matches the dropped node");
  ok(!canvas.classList.contains("drag-over"), "G: drop clears the drop-target state");

  // the rendered card literally sits at the drop point
  const cards = registry["#ws-nodes"].children;
  eq(cards[cards.length - 1].style.left, "160px", "G: card left renders at the drop client x");
  eq(cards[cards.length - 1].style.top, "90px", "G: card top renders at the drop client y");

  // pan/zoom + a non-zero canvas offset still map client → visible node:
  // (430-30-100)/2 = 150 and (150-40-50)/2 = 30 inside the canvas
  S.tx = 100; S.ty = 50; S.zoom = 2;
  canvas.getBoundingClientRect = () => ({ left: 30, top: 40 });
  canvas.dispatch("drop", {
    preventDefault() {},
    dataTransfer: { getData: () => "matthew" },
    clientX: 430, clientY: 150,
  });
  const nz = S.workflow.nodes[S.workflow.nodes.length - 1];
  eq(nz.x, 150 - ORIGIN, "G2: drop x respects pan/zoom/canvas offset");
  eq(nz.y, 30 - ORIGIN, "G2: drop y respects pan/zoom/canvas offset");
  eq(nz.x + ORIGIN, 150, "G2: rendered x == within-canvas drop x under transform");
  eq(nz.y + ORIGIN, 30, "G2: rendered y == within-canvas drop y under transform");
  S.tx = 0; S.ty = 0; S.zoom = 1;
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0 });

  // dropping an unknown/missing key is a no-op
  const afterUnknown = S.workflow.nodes.length;
  canvas.dispatch("drop", { preventDefault() {}, dataTransfer: { getData: () => "" }, clientX: 1, clientY: 1 });
  eq(S.workflow.nodes.length, afterUnknown, "G: empty drag payload does not create a node");

  // ── I. existing pointer-based move/connect handlers are preserved ──
  const nodeCard = registry["#ws-nodes"].children[0];
  ok((nodeCard._handlers.pointerdown || []).length === 1,
     "I: node card still binds pointerdown (move/connect preserved)");

  // ── J. search/filter narrows the available agents ──
  S.agentFilter = "alex";
  eq(matchingAgents().length, 1, "J: filter narrows to matching agents");
  eq(matchingAgents()[0].agent, "alex", "J: filter matches the agent name");
  S.agentFilter = "";

  console.log("workspace add-agent + drag/drop tests passed:", count);
}

main().catch((err) => {
  console.error("workspace add-agent tests FAILED:", err);
  process.exit(1);
});

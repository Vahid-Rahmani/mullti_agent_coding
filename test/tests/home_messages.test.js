"use strict";
/* Home agent-window presentation + user-message rendering tests —
   run with `node test/tests/home_messages.test.js`.

   Proves the agent window reads like a real agent session (identity → state →
   output) without inventing reasoning, and that a submitted message is
   rendered into the target window(s) immediately from frontend state:

     M1. Panels show an agent avatar (monogram) and a current-action line.
     M2. Real run statuses drive the status dot + current-action line
         (working…/completed/failed) — never fabricated text.
     M3. A submitted message renders into the entry-node window(s) at once.
     M4. A ``node:X`` target renders only into that node's window.
     M5. Marking nodes working flips their status to running/thinking.
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

/* ── DOM shim (same shape as home_drag_resize.test.js) ─────────────── */
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
  addEventListener() {}, removeEventListener() {},
  innerWidth: 1000, innerHeight: 800, localStorage,
};
global.document = document;
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

eval(src);

const { Ag, buildWorkspace, setHomeLayout, dispatchTargetNodes,
        renderUserMessage, markNodesWorking, setPanelRunStatus,
        nodeEvent } = global.window.MACApp;

const REGISTRY = [
  { tag: "m1", name: "Matthew", agent: "matthew" },
  { tag: "m2", name: "Alex", agent: "alex" },
];
const WF = {
  id: "wf-msg", name: "Msg",
  nodes: [
    { id: "n1", agent: "matthew", kind: "agent", label: "Matthew", x: 0, y: 0, model: "" },
    { id: "n2", agent: "alex", kind: "agent", label: "Alex", x: 100, y: 0, model: "" },
  ],
  edges: [{ source: "n1", target: "n2", condition: "" }],
};

function setActiveWorkflow(wf) {
  Ag.homeWorkflow = wf;
  Ag.homeNodes = (wf.nodes || []).filter((n) => n.kind === "agent");
  Ag.homeEdges = wf.edges || [];
}
function panelByNode(id) {
  return registry.grid.querySelector(`.panel[data-workflow-node-id="${id}"]`);
}
function consoleRows(id) {
  const p = panelByNode(id);
  return p ? p.querySelector(".p-console").children.map((c) => c.textContent) : [];
}
function nodeSession(id) {
  return (Ag.nodeSessions[id] || []).map((e) => e.text);
}

function main() {
  Ag.agents = REGISTRY.map((r) => Object.assign({}, r, {
    model: "", status: "idle", progress: 0, token_usage: 0, running: false, prompt: "",
  }));
  Ag.nodeSessions = {}; Ag.runStatuses = {};
  Ag.homeMode = "workflow"; Ag.homeZoom = 1; Ag.homeLayouts = {};
  storage.clear();

  setActiveWorkflow(WF);
  setHomeLayout("workflow");
  buildWorkspace();

  /* M1 — avatar + current-action line */
  const card = panelByNode("n1");
  const avatar = card.querySelector(".p-avatar");
  ok(avatar, "M1: panel has an agent avatar");
  eq(avatar.textContent, "M", "M1: avatar shows the agent monogram");
  eq(card.querySelector(".p-action").textContent, "idle", "M1: action line starts idle");

  /* M2 — real run status drives the status + action line */
  setPanelRunStatus(card, "running");
  ok(hasClass(card.querySelector(".p-status"), "st-busy"), "M2: running → busy dot");
  eq(card.querySelector(".p-status-label").textContent, "running", "M2: running label");
  eq(card.querySelector(".p-action").textContent, "working…", "M2: running → working…");
  setPanelRunStatus(card, "completed");
  ok(hasClass(card.querySelector(".p-status"), "st-ok"), "M2: completed → ok dot");
  eq(card.querySelector(".p-action").textContent, "completed", "M2: completed action");
  setPanelRunStatus(card, "failed");
  ok(hasClass(card.querySelector(".p-status"), "st-err"), "M2: failed → error dot");
  eq(card.querySelector(".p-action").textContent, "failed", "M2: failed action");

  /* M3 — submitted message renders into the entry node(s) immediately */
  renderUserMessage("workflow", "hello agents");
  deepEq(nodeSession("n1"), ["You: hello agents"], "M3: entry node session holds the message");
  deepEq(consoleRows("n1"), ["You: hello agents"], "M3: message rendered into the entry window");
  eq(nodeSession("n2").length, 0, "M3: non-entry node got no message");
  deepEq(dispatchTargetNodes("workflow").map((n) => n.id), ["n1"], "M3: entry nodes resolved");

  /* M4 — a node:X target renders only into that window */
  renderUserMessage("node:n2", "hi n2 only");
  deepEq(nodeSession("n2"), ["You: hi n2 only"], "M4: targeted node holds the message");
  deepEq(consoleRows("n2"), ["You: hi n2 only"], "M4: targeted window renders the message");
  deepEq(nodeSession("n1"), ["You: hello agents"], "M4: other node unaffected");

  /* M5 — marking nodes working flips their status */
  markNodesWorking(["n1", "n2"]);
  eq(Ag.runStatuses.n1, "running", "M5: run status recorded");
  eq(panelByNode("n1").querySelector(".p-status-label").textContent, "running", "M5: panel label running");
  eq(panelByNode("n1").querySelector(".p-action").textContent, "working…", "M5: panel action working…");
  ok(panelByNode("n1").classList.contains("running"), "M5: panel carries the running class");

  console.log("home messages tests passed:", count);
}

try {
  main();
} catch (err) {
  console.error("home messages tests FAILED:", err);
  process.exit(1);
}

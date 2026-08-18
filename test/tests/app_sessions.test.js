"use strict";
/* app.js agent-output session tests — run with `node test/tests/app_sessions.test.js`
   Loads the real scripts/web_ui/static/app.js into a minimal DOM shim and drives
   the live event → session → panel pipeline (onAgentEvent / buildWorkspace /
   openStream) exactly as the browser does.

   Regression coverage:
     A. events for a visible agent render normally
     B. events for a non-visible agent are NOT lost
     C. Ag.sessions[tag] holds received output even when no panel exists
     D. rebuilding the workspace with that agent now visible replays the output
     E. multiple SSE events for the same agent keep their order
     F. later layout changes never erase previously received output
     G. the SSE event protocol (event kinds / payload shape) is unchanged
   Plus: snapshot/init merge and per-agent tail cap. */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const APP_JS = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "app.js");
const src = fs.readFileSync(APP_JS, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function eq(a, b, msg) { count += 1; assert.strictEqual(a, b, msg); }
function deepEq(a, b, msg) {
  count += 1;
  assert.deepStrictEqual(a, b, msg);
}

/* ── minimal DOM shim ────────────────────────────────────────── */
function makeEl(tag) {
  const node = {
    tagName: tag,
    children: [],
    className: "",
    textContent: "",
    title: "",
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
    removeChild(c) {
      const i = this.children.indexOf(c);
      if (i >= 0) this.children.splice(i, 1);
      return c;
    },
    setAttribute(k, v) { this[k] = v; },
    addEventListener() {},
    querySelector(sel) { return query(this, sel); },
    querySelectorAll() { return []; },
  };
  return node;
}

function query(node, sel) {
  const m = sel.match(/^\.([\w-]+)(\[data-tag="([^"]+)"\])?$/);
  if (!m) return null;
  const wantCls = m[1];
  const wantTag = m[3];
  const stack = [node];
  while (stack.length) {
    const n = stack.pop();
    for (const c of n.children || []) {
      const cls = new Set(String(c.className || "").split(/\s+/).filter(Boolean));
      if (cls.has(wantCls) && (wantTag === undefined || c.dataset.tag === wantTag)) return c;
      stack.push(c);
    }
  }
  return null;
}

const registry = {
  grid: makeEl("div"),
  masterConsole: makeEl("div"),
  execConsole: makeEl("div"),
};

const document = {
  querySelector(sel) {
    if (sel === "#workspace-grid") return registry.grid;
    if (sel === "#master-console") return registry.masterConsole;
    if (sel === "#execution-console") return registry.execConsole;
    if (sel.startsWith(".panel[data-tag=")) return query(registry.grid, sel);
    return null; // e.g. "#status-table tr[data-tag=...]" → syncStatusRow no-ops
  },
  querySelectorAll(sel) {
    if (sel === ".panel") {
      return registry.grid.children.filter((child) =>
        String(child.className || "").split(/\s+/).includes("panel"));
    }
    return [];
  },
  createElement: (t) => makeEl(t),
  createElementNS: () => makeEl("g"),
  addEventListener() {},
  documentElement: {},
};

class MockEventSource {
  constructor(url) { this.url = url; this.onerror = null; this._h = {}; MockEventSource.last = this; }
  addEventListener(name, fn) { (this._h[name] = this._h[name] || []).push(fn); }
  _emit(name, data) { (this._h[name] || []).forEach((fn) => fn({ data: JSON.stringify(data) })); }
}

global.window = {
  GraphMath: {},
  addEventListener() {},
  MACSettings: undefined,
  sessionStorage: (() => {
    const values = new Map();
    return { getItem: (key) => values.get(key) || null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: (key) => values.delete(key) };
  })(),
  getComputedStyle: () => ({ getPropertyValue: () => "" }),
};
global.document = document;
global.EventSource = MockEventSource;
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

eval(src); // runs the IIFE; the DOMContentLoaded listener is never fired

async function main() {
const { Ag, onAgentEvent, buildWorkspace, panelEl, openStream, loadSessions,
        checkBackendRestart, saveStoredAgentSessions, loadStoredAgentSessions,
        nodeEvent, saveStoredNodeSessions, loadStoredNodeSessions } = global.window.MACApp;

const TAGS = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"];
const NAMES = { m1: "Matthew", m2: "Alex", m3: "Sarah", m4: "David",
                m5: "Elena", m6: "Max", m7: "Chloe" };
Ag.agents = TAGS.map((tag) => ({
  tag, name: NAMES[tag], agent: tag, model: "", status: "idle",
  progress: 0, token_usage: 0, running: false, prompt: "",
}));
// Home is a projection of the active workflow: panel visibility is driven by
// which agents have workflow nodes (not the legacy prefs.agents_visible list).
Ag.homeWorkflow = { id: "wf-test", name: "Test" };
Ag.homeEdges = [];
Ag.nodeSessions = {};
Ag.runStatuses = {};
Ag.sessions = {};
const showAgents = (tags) => {
  Ag.homeNodes = tags.map((tag, i) => ({
    id: "n_" + tag, agent: tag, label: NAMES[tag],
    x: 100 + i * 120, y: 100, model: "", kind: "agent",
  }));
};
showAgents(["m1", "m2", "m3", "m4", "m5", "m6"]);

const rows = (tag) => {
  const p = query(registry.grid, `.panel[data-tag="${tag}"]`);
  return p ? p.querySelector(".p-console").children.map((c) => c.textContent) : [];
};
const sessTexts = (tag) => (Ag.sessions[tag] || []).map((e) => e.text);

/* A — visible agent renders normally */
buildWorkspace();
onAgentEvent("m4", { n: 1, tag: "m4", kind: "run", text: "M4::hello" });
onAgentEvent("m4", { n: 2, tag: "m4", kind: "line", text: "output line" });
ok(query(registry.grid, '.panel[data-tag="m4"]'), "A: m4 panel exists");
deepEq(rows("m4"), ["M4::hello", "output line"], "A: run + line rendered into m4 panel");
deepEq(sessTexts("m4"), ["M4::hello", "output line"], "A: session mirrors rendered events");

/* B/C — non-visible workflow node text is NOT lost; node session holds output */
nodeEvent("n_m7", {
  n: 3, tag: "m7", session_id: "workflow:wf-test:n_m7:freebuff/auto",
  kind: "line", text: "m7 secret output",
});
ok(panelEl("m7") === null, "B: m7 has no rendered panel at layout 4");
eq(Ag.nodeSessions.n_m7.length, 1, "B: m7 event was not discarded");
eq(Ag.nodeSessions.n_m7[0].text, "m7 secret output", "C: node session holds hidden output");

/* D — rebuild with the agent now visible replays previous output
   (the UI renders at most 6 of the 7 panels, so m7 becomes visible by
   swapping it into the visible set) */
showAgents(["m1", "m2", "m3", "m4", "m5", "m7"]);
buildWorkspace();
ok(panelEl("m7"), "D: m7 panel rendered after layout/visibility change");
deepEq(rows("m7"), ["m7 secret output"], "D: previously hidden output replayed on visibility");

/* E — multiple events for the same agent preserve order */
["one", "two", "three"].forEach((t, i) =>
  nodeEvent("n_m7", { n: 10 + i, tag: "m7",
    session_id: "workflow:wf-test:n_m7:freebuff/auto", kind: "line", text: t }));
deepEq(Ag.nodeSessions.n_m7.map((e) => e.text),
       ["m7 secret output", "one", "two", "three"], "E: session order preserved");
buildWorkspace();
deepEq(rows("m7"), ["m7 secret output", "one", "two", "three"], "E: rendered order preserved");

/* F — later layout changes never erase received output */
showAgents(["m1", "m2", "m3", "m4", "m5", "m6"]);
buildWorkspace();
ok(panelEl("m7") === null, "F: m7 hidden again");
showAgents(["m1", "m2", "m3", "m4", "m5", "m7"]);
buildWorkspace();
deepEq(rows("m7"), ["m7 secret output", "one", "two", "three"], "F: toggles never erase output");

/* F2 — a Home → Workflow → Home page navigation restores panel history. */
saveStoredNodeSessions();
Ag.nodeSessions = {};
Ag.nodeSessionsWorkflowId = null;
Ag.nodeSessions = loadStoredNodeSessions("wf-test");
deepEq(Ag.nodeSessions.n_m7.map((e) => e.text),
       ["m7 secret output", "one", "two", "three"],
       "F2: session storage restores panel history after navigation");

/* G — SSE protocol compatibility (driven through the real openStream handler) */
showAgents(["m1", "m2", "m3", "m4"]);
buildWorkspace();
openStream();
const es = MockEventSource.last;
ok(es, "G: openStream opened an EventSource");
es._emit("line", { n: 20, tag: "m4", kind: "line", text: "via sse" });
ok(rows("m4").includes("via sse"), "G: SSE line event rendered to visible panel");
ok(sessTexts("m4").includes("via sse"), "G: SSE event persisted");
const sessLen = Ag.sessions.m4.length;
es._emit("line", { n: 20, tag: "m4", kind: "line", text: "via sse" }); // duplicate backend seq
eq(Ag.sessions.m4.length, sessLen, "G: duplicate backend seq (n) de-duplicated");
es._emit("run", { n: 21, tag: "m5", kind: "run", text: "M5::hidden run" });
ok(panelEl("m5") === null, "G: m5 not rendered at layout 4");
ok(sessTexts("m5").includes("M5::hidden run"), "G: hidden-agent SSE event persisted");
es._emit("line", { n: 22, tag: "master", kind: "line", text: "▶ prompt" });
ok(registry.masterConsole.children.some((c) => c.textContent === "▶ prompt"),
   "G: master console still receives master events (Status tab unchanged)");
es._emit("usermsg", { n: 23, tag: "m6", kind: "usermsg", text: "▶ dispatched (target=m6)" });
ok(sessTexts("m6").includes("▶ dispatched (target=m6)"), "G: usermsg persisted for hidden agent");
// status events are persisted but never rendered as console rows (dot only)
es._emit("status", { n: 24, tag: "m4", kind: "status", text: "thinking" });
ok(sessTexts("m4").includes("thinking"), "G: status event persisted");
ok(!rows("m4").includes("thinking"), "G: status never rendered as a console row");
showAgents(["m1", "m2", "m3", "m4", "m5", "m6"]);
buildWorkspace();
ok(!rows("m4").includes("thinking"), "G: status not replayed as a row either (live == replay)");
showAgents(["m1", "m2", "m3", "m4"]);
buildWorkspace();

/* H — raw PTY bytes are live-only transport and never replay history. */
Ag.sessions = {};
Ag.rawEventKeys = {};
Ag.sessionGenerations = {};
Ag.backendGeneration = null;
Ag.backendEpoch = 0;
showAgents(["m1"]);
buildWorkspace();
const rawSession = "agent:m1:freebuff/auto";
const rawEvent = {
  n: 50, seq: 50, tag: "m1", session_id: rawSession,
  session_generation: "generation-a", kind: "line", raw: true,
  text: "\\x1b[?1049hLIVE-TUI",
};
onAgentEvent("m1", rawEvent);
eq((Ag.sessions[rawSession] || []).length, 0, "H: raw event is not persisted");
eq(rows("m1").length, 1, "H: live raw event renders once");
buildWorkspace();
eq(rows("m1").length, 0, "H: remount starts clean and does not replay raw ANSI");
onAgentEvent("m1", rawEvent);
eq(rows("m1").length, 0, "H: already-seen live raw event is not rendered twice");
window.sessionStorage.setItem("zova-home-agent-sessions", JSON.stringify({
  [rawSession]: [rawEvent, { n: 51, tag: "m1", kind: "line", text: "TEXT" }],
}));
loadStoredAgentSessions();
eq((Ag.sessions[rawSession] || []).length, 1, "H: browser replay migration keeps text only");
eq(Ag.sessions[rawSession][0].text, "TEXT", "H: browser replay migration drops raw bytes");

/* I — reused n/seq values from a new backend generation remain distinct. */
onAgentEvent("m1", {
  n: 50, seq: 50, tag: "m1", session_id: rawSession,
  session_generation: "generation-b", kind: "line", raw: true,
  text: "NEW-GENERATION",
});
eq(Ag.backendEpoch, 1, "I: backend generation change opens a new epoch");
eq(rows("m1").length, 1, "I: reused n/seq from a new generation is accepted once");

/* init-snapshot merge: snapshot arriving after live events must not revert them */
showAgents(["m1", "m2"]);
const m2Session = "workflow:wf-test:n_m2:freebuff/auto";
onAgentEvent("m2", { n: 1, tag: "m2", session_id: m2Session, kind: "line", text: "a" });
onAgentEvent("m2", { n: 2, tag: "m2", session_id: m2Session, kind: "line", text: "b" });
onAgentEvent("m2", { n: 3, tag: "m2", session_id: m2Session, kind: "line", text: "c" });
global.fetch = async () => ({
  ok: true,
  json: async () => ({
    sessions: {
      [m2Session]: [1, 2, 3, 4, 5].map((n) => ({
        n, tag: "m2", session_id: m2Session, kind: "line", text: String.fromCharCode(96 + n),
      })),
    },
  }),
});
await loadSessions();
deepEq((Ag.sessions[m2Session] || []).map((e) => e.text), ["a", "b", "c", "d", "e"],
       "snapshot merge adds the missing prefix and never reverts live events");
deepEq(rows("m2"), ["a", "b", "c", "d", "e"],
       "replay renders the merged session once");
const m2RowCount = rows("m2").length;
es._emit("line", { n: 3, tag: "m2", session_id: m2Session, kind: "line", text: "c" }); // already replayed from snapshot
ok(rows("m2").length === m2RowCount, "snapshot-replayed event is not double-appended live");

/* per-agent tail cap */
for (let i = 0; i < 810; i++) {
  onAgentEvent("m1", { n: 1000 + i, tag: "m1", kind: "line", text: "filler" + i });
}
ok(Ag.sessions.m1.length <= 800, "session capped at SESSION_TAIL");

/* backend-restart regression: WebState "n" resets to 0 on a restart, so the old
   session's n=1.. collide with the new process's events. Preserve history and
   use a new epoch so the n-dedup never swallows the new run's output.
   Self-contained: the old-process watermark is established explicitly here so
   the test does not depend on earlier sections having run. */
showAgents(["m1", "m2", "m4"]);
buildWorkspace();
checkBackendRestart(5);   // old process had reached backend sequence n=5
Ag.sessions.m4 = [{ n: 1, tag: "m4", kind: "line", text: "OLD OUTPUT" }];
ok(checkBackendRestart(0), "backend restart detected when the sequence regresses");
ok(sessTexts("m4").includes("OLD OUTPUT"), "restart preserves existing panel history");
onAgentEvent("m4", { n: 1, tag: "m4", kind: "line", text: "NEW PONG" });
ok(sessTexts("m4").includes("NEW PONG"), "new run output persisted after a backend restart");
ok(rows("m4").includes("NEW PONG"), "new run output renders after a backend restart");

console.log("app.js session tests passed:", count);
}

main().catch((err) => {
  console.error("app.js session tests FAILED:", err);
  process.exit(1);
});

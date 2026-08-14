"use strict";
/* Phase 2 Task → Prompt recommendation behavioral tests — run with
   `node test/tests/workspace_prompt_recommendation.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves:

     A. nodeTaskDescription reads the node's Task/Purpose text
     B. nodePromptRole maps a node's role/agent to a prompt role
     C. suggestPrompt POSTs /api/prompts/recommend and stores task + recs
     D. the recommendation preview renders ranked items with a score
     E. the model-requirements preview renders the preference table
     F. applying a recommendation fills an empty Instruction (safe apply)
     G. a recommendation never changes the node's explicit model
     H. template loading preserves task + prompt_profile (and never merges)
*/

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const WS_JS = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "workspace.js");
const src = fs.readFileSync(WS_JS, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function eq(a, b, msg) { count += 1; assert.strictEqual(a, b, msg); }
function de(a, b, msg) { count += 1; assert.deepStrictEqual(a, b, msg); }

function makeEl(tag) {
  return {
    tagName: tag,
    children: [],
    className: "",
    textContent: "",
    title: "",
    value: "",
    label: "",
    type: "",
    dataset: {},
    style: {},
    hidden: false,
    clientWidth: 800,
    clientHeight: 600,
    parentNode: null,
    attrs: {},
    _handlers: {},
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
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); },
    dispatch(type, ev) { (this._handlers[type] || []).forEach((fn) => fn(ev || {})); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    contains() { return false; },
    focus() {},
    getBoundingClientRect() { return { left: 0, top: 0 }; },
    get firstChild() { return this.children[0] || null; },
  };
}

const registry = {
  "ws-status": makeEl("div"),
  "ws-dirty": makeEl("div"),
  "ws-activate": makeEl("button"),
  "ws-workflow-select": makeEl("select"),
  "ws-template-select": makeEl("select"),
  "ws-template-load": makeEl("button"),
  "ws-props-body": makeEl("div"),
  "ws-world": makeEl("div"),
  "ws-edges": makeEl("svg"),
  "ws-nodes": makeEl("div"),
  "ws-canvas": makeEl("div"),
  "ws-empty-hint": makeEl("div"),
  "ws-library-list": makeEl("div"),
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
  createElement: (t) => makeEl(t),
  createElementNS: () => makeEl("g"),
};

global.window = {
  addEventListener() {},
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  prompt() { return null; },
  confirm() { return false; },
};
global.document = document;
global.requestAnimationFrame = (cb) => { cb(); return 0; };

const PROMPT_LIST = [
  { id: "security-auditor", name: "Security Auditor", description: "Finds vulnerabilities.",
    role: "security_engineer", category: "security", capabilities: ["security", "vulnerability analysis", "audit"],
    recommended_models: [], tags: ["security", "audit"], version: "1.0.0",
    model_preferences: { reasoning: "high", coding: "medium", context: "large",
                         tool_use: "medium", latency: "medium", cost: "medium" } },
  { id: "security-appsec-engineer", name: "Application Security Engineer",
    role: "security_engineer", category: "security",
    capabilities: ["security", "secure coding", "vulnerability analysis"],
    recommended_models: [], tags: ["security"], version: "1.0.0",
    model_preferences: { reasoning: "high", coding: "medium", context: "large",
                         tool_use: "medium", latency: "medium", cost: "medium" } },
];
const PROMPT_TEXTS = {
  "security-auditor": "You are a security auditor. Map the attack surface.",
  "security-appsec-engineer": "You are an appsec engineer.",
};

let requests = [];
let fetchImpl = null;
global.fetch = async (p, opts) => {
  requests.push({ path: p, opts });
  if (!fetchImpl) throw new Error("no fetch handler");
  return fetchImpl(p, opts);
};
function jsonRes(status, data) {
  return { ok: status >= 200 && status < 300, status, statusText: String(status),
           json: async () => data };
}
function reset() { requests = []; fetchImpl = null; }

eval(src);

const { S, loadMeta, nodeTaskDescription, nodePromptRole, suggestPrompt,
        renderRecommendationPreview, renderModelCapabilityPreview,
        onPromptSelected, loadTemplate } = global.window.MACWorkspace;

async function main() {
  /* ── A/B: task text + prompt-role mapping ── */
  eq(nodeTaskDescription({ task: { description: "audit auth" } }), "audit auth",
     "A: reads task.description");
  eq(nodeTaskDescription({ task: { context: "from context" } }), "from context",
     "A: falls back to task.context");
  eq(nodeTaskDescription({}), "", "A: empty when no task metadata");

  S.prompts = PROMPT_LIST;
  S.promptById = {};
  PROMPT_LIST.forEach((p) => { S.promptById[p.id] = p; });
  eq(nodePromptRole({ agent: "matthew", roles: ["python-developer"] }), "software_engineer",
     "B: role id maps to a prompt role");
  S.roleAssignments = { matthew: ["security-engineer"] };
  eq(nodePromptRole({ agent: "matthew", roles: [] }), "security_engineer",
     "B: falls back to agent role assignments");
  eq(nodePromptRole({ agent: "zzz", roles: [] }), null, "B: unknown agent → null");
  S.roleAssignments = {};

  /* ── C: suggestPrompt POSTs and stores task + recs ── */
  reset();
  const n = { id: "n1", agent: "alex", kind: "agent", roles: ["security-engineer"],
              model: "google/gemini-3.5-flash-lite", instructions: "",
              task: { description: "audit auth flow" } };
  S.taskRecs = {};
  fetchImpl = async (p, opts) => {
    if (p === "/api/prompts/recommend" && opts.method === "POST") {
      const body = JSON.parse(opts.body);
      eq(body.task, "audit auth flow", "C: task text sent");
      eq(body.role, "security_engineer", "C: mapped role sent");
      return jsonRes(200, {
        task: { category: "security", capabilities: ["security", "audit"],
                complexity: "medium", risk: "high", context: "audit auth flow" },
        recommendations: [
          { prompt_id: "security-auditor", score: 0.95, reason: "Matches security; audit." },
          { prompt_id: "security-appsec-engineer", score: 0.6, reason: "Matches security." },
        ],
      });
    }
    throw new Error("unexpected fetch: " + p);
  };
  const recs = await suggestPrompt(n);
  eq(recs.length, 2, "C: recommendations returned");
  eq(n.task.category, "security", "C: classification persisted on the node");
  eq(n.task.description, "audit auth flow", "C: description persisted");
  de(S.taskRecs["n1"].map((r) => r.prompt_id),
     ["security-auditor", "security-appsec-engineer"], "C: recs stored by node id");

  /* ── D: recommendation preview renders ranked items ── */
  const body = makeEl("div");
  renderRecommendationPreview(body, n);
  const wrap = body.children.find((c) => c.className === "ws-recs");
  ok(wrap, "D: recommendations wrapper rendered");
  const recItems = wrap.children.filter((c) => c.className && c.className.indexOf("ws-rec-item") === 0);
  eq(recItems.length, 2, "D: two recommendation items rendered");
  eq(recItems[0].children[0].textContent, "Security Auditor", "D: first item is the top-ranked");
  eq(recItems[0].children[1].textContent, "95% match", "D: score rendered as a percentage");
  const note = wrap.children.find((c) => c.className === "ws-recs-note");
  ok(note && (note.textContent || "").indexOf("deterministic matching scores") !== -1,
     "D: note clarifies the score is deterministic, not AI confidence");

  /* ── E: model-requirements preview ── */
  n.prompt_profile = "security-auditor";
  const body2 = makeEl("div");
  renderModelCapabilityPreview(body2, n);
  const prefs = body2.children.find((c) => c.className === "ws-model-prefs");
  ok(prefs, "E: model-requirements block rendered");
  const rows = prefs.children[1].children;
  ok(rows.length >= 6, "E: requirement rows rendered");

  /* ── F/G: applying a recommendation is safe + never touches the model ── */
  reset();
  fetchImpl = async (p) => {
    if (p.startsWith("/api/prompts/")) {
      const id = decodeURIComponent(p.slice("/api/prompts/".length));
      if (PROMPT_TEXTS[id] === undefined) return jsonRes(404, { detail: "unknown" });
      return jsonRes(200, { prompt: { prompt: PROMPT_TEXTS[id], id, name: id } });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await onPromptSelected(n, "security-auditor");
  eq(n.prompt_profile, "security-auditor", "F: recommendation applies the prompt profile");
  eq(n.instructions, PROMPT_TEXTS["security-auditor"], "F: empty instruction auto-filled");
  eq(n.model, "google/gemini-3.5-flash-lite", "G: explicit model is never overwritten");

  /* ── H: template loading preserves task + prompt_profile, never merges ── */
  reset();
  const TEMPLATE = {
    id: "template-t", name: "T", project: "",
    nodes: [{ id: "n1", label: "Dev", agent: "matthew", kind: "agent",
              prompt_profile: "security-auditor",
              task: { description: "audit", category: "security" }, model: "" }],
    edges: [], entry: ["n1"], state: {}, settings: { max_iterations: 3 },
  };
  registry["ws-template-select"].value = "t";
  fetchImpl = async (p) => {
    if (p === "/api/workflows/from-template/t") {
      return jsonRes(200, { workflow: JSON.parse(JSON.stringify(TEMPLATE)) });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await loadTemplate();
  eq(S.workflow.nodes.length, 1, "H: template fully replaced (no merge)");
  eq(S.workflow.nodes[0].prompt_profile, "security-auditor", "H: prompt_profile preserved");
  de(S.workflow.nodes[0].task, { description: "audit", category: "security" },
     "H: task metadata preserved");

  console.log("workspace prompt recommendation tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

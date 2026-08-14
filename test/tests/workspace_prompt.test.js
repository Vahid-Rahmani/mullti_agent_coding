"use strict";
/* Prompt Library → Workspace behavioral tests — run with
   `node test/tests/workspace_prompt.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   the Prompt Profile → Instruction flow:

     A. loadMeta fetches /api/prompts and populates S.prompts + S.promptById
     B. suggestPromptRole maps roles/agents/keywords deterministically
     C. suggestPromptsForNode filters prompts by the node's role/agent
     D. selecting a prompt with an empty Instruction auto-fills it
     E. selecting a prompt with a custom Instruction never overwrites it
     F. Apply Prompt explicitly replaces the Instruction
     G. fetchPromptText caches the full prompt text
     H. prompt_profile is stored on the node (persists in the workflow payload)
     I. template loading preserves prompt_profile on its nodes
     J. a template without prompt_profile still loads (backward compatible)
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

/* ── minimal DOM shim (same surface as the template test) ────────── */
function makeEl() {
  return {
    textContent: "",
    className: "",
    title: "",
    value: "",
    innerHTML: "",
    style: {},
    dataset: {},
    hidden: false,
    clientWidth: 800,
    clientHeight: 600,
    attrs: {},
    firstChild: null,
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
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener() {},
    appendChild() {},
    removeChild() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

const registry = {
  "ws-status": makeEl(),
  "ws-dirty": makeEl(),
  "ws-activate": makeEl(),
  "ws-workflow-select": makeEl(),
  "ws-template-select": makeEl(),
  "ws-template-load": makeEl(),
  "ws-props-body": makeEl(),
  "ws-world": makeEl(),
  "ws-edges": makeEl(),
  "ws-nodes": makeEl(),
  "ws-canvas": makeEl(),
  "ws-empty-hint": makeEl(),
  "ws-library-list": makeEl(),
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
global.requestAnimationFrame = (cb) => { cb(); return 0; };

/* ── fetch stub ─────────────────────────────────────────────────── */
const PROMPT_LIST = [
  { id: "software-engineer", name: "Software Engineer", description: "General engineering.",
    role: "software_engineer", category: "development", capabilities: ["coding", "debugging"],
    recommended_models: [], tags: ["engineering"], version: "1.0.0" },
  { id: "software-engineer-expert", name: "Expert Software Engineer", description: "Senior level.",
    role: "software_engineer", category: "development", capabilities: ["coding", "refactoring"],
    recommended_models: [], tags: ["senior"], version: "1.0.0" },
  { id: "security-auditor", name: "Security Auditor", description: "Finds vulnerabilities.",
    role: "security_engineer", category: "security", capabilities: ["security", "audit"],
    recommended_models: [], tags: ["security"], version: "1.0.0" },
];
const PROMPT_TEXTS = {
  "software-engineer": "You are a careful software engineer. Inspect existing code.",
  "software-engineer-expert": "You are an expert engineer operating at a senior level.",
  "security-auditor": "You are a security auditor. Map the attack surface.",
};

let requests = [];
let fetchImpl = null;
global.fetch = async (p, opts) => {
  requests.push({ path: p, opts });
  if (!fetchImpl) throw new Error("no fetch handler registered");
  return fetchImpl(p, opts);
};
function jsonRes(status, data) {
  return { ok: status >= 200 && status < 300, status, statusText: String(status),
           json: async () => data };
}
function reset() {
  requests = [];
  fetchImpl = null;
  registry["ws-status"].textContent = "";
  registry["ws-status"].className = "";
}

eval(src); // IIFE runs; init() is NOT called (readyState === "loading")

const { S, loadMeta, suggestPromptRole, suggestPromptsForNode, fetchPromptText,
        applyPromptToNode, onPromptSelected, loadTemplate } = global.window.MACWorkspace;

function fetchPromptsHandler() {
  return async (p, opts) => {
    if (p === "/api/agents") return jsonRes(200, { agents: [] });
    if (p === "/api/settings/roles") return jsonRes(200, { roles: [], assignments: {} });
    if (p === "/api/settings/models") return jsonRes(200, { available: [] });
    if (p === "/api/connections") return jsonRes(200, { connections: [], providers: [] });
    if (p === "/api/prompts") {
      return jsonRes(200, { prompts: PROMPT_LIST, roles: [] });
    }
    if (p.startsWith("/api/prompts/")) {
      const id = decodeURIComponent(p.slice("/api/prompts/".length));
      const text = PROMPT_TEXTS[id];
      if (text === undefined) return jsonRes(404, { detail: `unknown prompt profile '${id}'` });
      return jsonRes(200, { prompt: Object.assign({ prompt: text },
        PROMPT_LIST.find((x) => x.id === id)) });
    }
    throw new Error("unexpected fetch: " + p);
  };
}

async function main() {
  /* ── A: loadMeta populates S.prompts + S.promptById ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  await loadMeta();
  eq(S.prompts.length, 3, "A: prompt metadata loaded from /api/prompts");
  eq(S.promptById["software-engineer-expert"].name, "Expert Software Engineer",
     "A: promptById index built");

  /* ── B: deterministic role/keyword mapping ── */
  eq(suggestPromptRole("developer"), "software_engineer", "B: developer → software_engineer");
  eq(suggestPromptRole("python-developer"), "software_engineer", "B: python-developer → software_engineer");
  eq(suggestPromptRole("architect"), "software_architect", "B: architect → software_architect");
  eq(suggestPromptRole("security"), "security_engineer", "B: security → security_engineer");
  eq(suggestPromptRole("ai-agent-engineer"), "ai_engineer", "B: ai-agent-engineer → ai_engineer (specific wins)");
  eq(suggestPromptRole("software_engineer"), "software_engineer", "B: exact role matches");
  eq(suggestPromptRole("matthew"), null, "B: unknown key → null");
  eq(suggestPromptRole(""), null, "B: empty → null");

  /* ── C: suggestPromptsForNode filters by role ── */
  const devNode = { agent: "matthew", roles: ["python-developer"] };
  de(suggestPromptsForNode(devNode).map((p) => p.id),
     ["software-engineer", "software-engineer-expert"], "C: developer role → software engineer prompts");
  const secNode = { agent: "alex", roles: ["security-engineer"] };
  de(suggestPromptsForNode(secNode).map((p) => p.id), ["security-auditor"],
     "C: security role → security prompts");
  // falls back to the agent's persistent assignments when the node has no roles
  S.roleAssignments = { matthew: ["security-engineer"] };
  de(suggestPromptsForNode({ agent: "matthew", roles: [] }).map((p) => p.id),
     ["security-auditor"], "C: falls back to agent role assignments");
  S.roleAssignments = {};

  /* ── D: selecting a prompt with empty instructions auto-fills ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  const empty = { agent: "matthew", kind: "agent", roles: [], instructions: "" };
  await onPromptSelected(empty, "software-engineer-expert");
  eq(empty.prompt_profile, "software-engineer-expert", "D: prompt_profile stored on the node");
  eq(empty.instructions, PROMPT_TEXTS["software-engineer-expert"],
     "D: empty instruction is auto-filled from the prompt");

  /* ── E: a custom instruction is never silently overwritten ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  const custom = { agent: "matthew", kind: "agent", roles: [], instructions: "Keep me" };
  await onPromptSelected(custom, "software-engineer-expert");
  eq(custom.prompt_profile, "software-engineer-expert", "E: prompt_profile stored");
  eq(custom.instructions, "Keep me", "E: custom instruction is preserved");

  /* ── F: Apply Prompt explicitly replaces the instruction ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  await applyPromptToNode(custom, "software-engineer-expert");
  eq(custom.instructions, PROMPT_TEXTS["software-engineer-expert"],
     "F: Apply Prompt replaces the instruction");

  /* ── G: fetchPromptText caches ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  const t1 = await fetchPromptText("security-auditor");
  const reqCount = requests.length;
  const t2 = await fetchPromptText("security-auditor");
  eq(t1, PROMPT_TEXTS["security-auditor"], "G: fetchPromptText returns the full text");
  eq(t2, t1, "G: second call returns the cached value");
  eq(requests.length, reqCount, "G: cached prompt text does not refetch");

  /* ── H: prompt_profile is part of the node payload (persists) ── */
  ok("prompt_profile" in empty && empty.prompt_profile === "software-engineer-expert",
     "H: node carries prompt_profile for persistence");

  /* ── I: template loading preserves prompt_profile ── */
  reset();
  const TEMPLATE = {
    id: "template-prompted", name: "Prompted", project: "",
    nodes: [{ id: "n1", label: "Dev", agent: "matthew", kind: "agent",
              prompt_profile: "software-engineer-expert", instructions: "Keep", model: "" }],
    edges: [], entry: ["n1"], state: {}, settings: { max_iterations: 3 },
  };
  registry["ws-template-select"].value = "prompted";
  fetchImpl = async (p, opts) => {
    if (p === "/api/workflows/from-template/prompted") {
      return jsonRes(200, { workflow: JSON.parse(JSON.stringify(TEMPLATE)) });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await loadTemplate();
  eq(S.workflow.id, "template-prompted", "I: template fully replaced the workflow");
  eq(S.workflow.nodes[0].prompt_profile, "software-engineer-expert",
     "I: prompt_profile survives template loading");
  eq(S.workflow.nodes[0].instructions, "Keep", "I: custom instruction survives template loading");

  /* ── J: old template without prompt_profile still loads ── */
  reset();
  const OLD_TEMPLATE = {
    id: "template-old", name: "Old", project: "",
    nodes: [{ id: "n1", label: "Dev", agent: "matthew", kind: "agent", model: "" }],
    edges: [], entry: ["n1"], state: {}, settings: { max_iterations: 3 },
  };
  registry["ws-template-select"].value = "old";
  fetchImpl = async (p) => {
    if (p === "/api/workflows/from-template/old") {
      return jsonRes(200, { workflow: JSON.parse(JSON.stringify(OLD_TEMPLATE)) });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await loadTemplate();
  eq(S.workflow.nodes[0].prompt_profile, undefined,
     "J: template without prompt_profile loads with no profile (backward compatible)");

  /* ── K: selecting a profile renames an auto-derived node label ──
     Bug fix: the Prompt Profile is the canonical title source — when the
     label is auto-derived (label_auto not false) the canvas node title
     follows the selected profile so sidebar and canvas can't diverge. */
  reset();
  fetchImpl = fetchPromptsHandler();
  const autoNode = { id: "n1", label: "Matthew", label_auto: true,
                     agent: "matthew", kind: "agent", roles: [], instructions: "" };
  await onPromptSelected(autoNode, "software-engineer-expert");
  eq(autoNode.label, "Expert Software Engineer",
     "K: auto label follows the selected prompt profile");
  eq(autoNode.prompt_profile, "software-engineer-expert", "K: prompt_profile stored");

  /* ── L: a user-customized label is never overwritten by a profile change ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  const customNode = { id: "n1", label: "My Custom Node", label_auto: false,
                       agent: "matthew", kind: "agent", roles: [], instructions: "" };
  await onPromptSelected(customNode, "software-engineer-expert");
  eq(customNode.label, "My Custom Node",
     "L: custom label is preserved when the profile changes");

  /* ── M: label_auto persists on the node (survives save/reload) ── */
  reset();
  fetchImpl = fetchPromptsHandler();
  const persistNode = { id: "n1", label: "Matthew", label_auto: false,
                        agent: "matthew", kind: "agent", roles: [], instructions: "" };
  await onPromptSelected(persistNode, "software-engineer-expert");
  ok(persistNode.label_auto === false && "label_auto" in persistNode,
     "M: label_auto is part of the node payload (custom flag survives round-trips)");
  eq(persistNode.label, "Matthew", "M: persisted custom flag keeps the name stable");

  console.log("workspace prompt tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

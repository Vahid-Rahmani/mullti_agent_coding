"use strict";
/* Phase 4 BYOK connection UI tests — run with
   `node test/tests/workspace_connections.test.js`.

   Loads the real scripts/web_ui/static/workspace.js into a DOM shim and proves
   the Connection control + Manage Connections manager:

     A. loadConnections fetches /api/connections (metadata only)
     B. connectionCombo offers Auto / Local / each connection and persists the
        selected connection_id onto the node (never a secret)
     C. providerForNode derives the provider from the model id
     D. the manager renders connection cards with status + Validate/Edit/Delete
     E. editing never displays a stored secret (masked marker + Replace Key)
     F. the API key is never placed into JS state or DOM text
     G. create/update/delete go through the /api/connections endpoints
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
  return {
    tagName: tag,
    children: [],
    className: "",
    textContent: "",
    title: "",
    value: "",
    type: "",
    placeholder: "",
    disabled: false,
    checked: false,
    dataset: {},
    style: {},
    attrs: {},
    parentNode: null,
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
    focus() {},
    get firstChild() { return this.children[0] || null; },
  };
}

const registry = {
  "ws-status": makeEl("div"),
  "ws-dirty": makeEl("div"),
  "ws-activate": makeEl("button"),
  "ws-workflow-select": makeEl("select"),
  "ws-template-select": makeEl("select"),
  "ws-props-body": makeEl("div"),
  "ws-world": makeEl("div"),
  "ws-edges": makeEl("svg"),
  "ws-nodes": makeEl("div"),
  "ws-canvas": makeEl("div"),
  "ws-empty-hint": makeEl("div"),
  "ws-library-list": makeEl("div"),
  "ws-conn-mgr": makeEl("div"),
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

const CONFIRMS = [];
global.window = {
  addEventListener() {},
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  prompt() { return null; },
  confirm() { CONFIRMS.push(arguments[0]); return true; },
};
global.document = document;
global.requestAnimationFrame = (cb) => { cb(); return 0; };

/* ── fetch stub ────────────────────────────────────────────────── */
let requests = [];
let fetchImpl = null;
global.fetch = async (p, opts) => {
  requests.push({ path: p, opts });
  if (!fetchImpl) throw new Error("no fetch handler registered");
  return fetchImpl(p, opts);
};
function jsonRes(status, data) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => data,
  };
}

eval(src); // IIFE runs; init() is NOT called (readyState === "loading")

const { S, loadConnections, connectionById, providerForNode, connectionCombo,
        openConnectionManager, renderConnectionManager } = global.window.MACWorkspace;

const SECRET = "test-secret-value-abc123";
const CONNECTIONS = [
  { id: "conn_openai_1", connection_id: "conn_openai_1", provider: "openai",
    display_name: "OpenAI Primary", credential_type: "api_key",
    endpoint: "", deployment: "", status: "configured", default: false },
  { id: "conn_ollama_1", connection_id: "conn_ollama_1", provider: "ollama",
    display_name: "Local Ollama", credential_type: "none",
    endpoint: "", deployment: "", status: "configured", default: false },
];
const PROVIDERS = [
  { provider: "openai", display_name: "OpenAI", requires_api_key: true },
  { provider: "anthropic", display_name: "Anthropic", requires_api_key: true },
  { provider: "ollama", display_name: "Ollama (local)", requires_api_key: false },
];

function connsHandler(extra) {
  return async (p, opts) => {
    if (p === "/api/connections" && (!opts || !opts.method || opts.method === "GET")) {
      return jsonRes(200, { connections: CONNECTIONS, providers: PROVIDERS });
    }
    if (extra) return extra(p, opts);
    throw new Error("unexpected fetch: " + p + " " + JSON.stringify(opts));
  };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

async function main() {
  /* ── A: loadConnections populates metadata (never secrets) ── */
  fetchImpl = connsHandler();
  await loadConnections();
  eq(S.connections.length, 2, "A: connections loaded");
  eq(S.connectionProviders.length, 3, "A: provider metadata loaded");
  eq(connectionById("conn_openai_1").provider, "openai", "A: id lookup");
  eq(connectionById("nope"), null, "A: unknown id → null");

  /* ── C: provider derived from model id ── */
  eq(providerForNode({ model: "openai/gpt-5" }), "openai", "C: provider from model");
  eq(providerForNode({ model: "ollama/qwen2.5-coder:7b" }), "ollama", "C: local provider");
  eq(providerForNode({ model: "" }), "", "C: empty model → no provider");
  eq(providerForNode({}), "", "C: no model → no provider");

  /* ── B: connection combo offers Auto/Local/connections + persists id ── */
  const node = { id: "n1", agent: "matthew", kind: "agent", model: "openai/gpt-5", connection_id: "" };
  const combo = connectionCombo(node);
  const sel = combo.children[0];
  eq(sel.children.length, 2 + CONNECTIONS.length, "B: Auto + Local + connections");
  eq(sel.children[0].value, "", "B: Auto option");
  eq(sel.children[1].value, "local", "B: Local / None option");
  eq(sel.children[2].value, "conn_openai_1", "B: connection option");
  sel.value = "conn_openai_1";
  sel.dispatch("change");
  eq(node.connection_id, "conn_openai_1", "B: selection persisted onto the node");
  eq(S.dirty, true, "B: selection marks the workflow dirty");
  const manageBtn = combo.children[1];
  eq(manageBtn.textContent, "Manage Connections", "B: Manage Connections button");

  /* ── D: manager renders cards with status + actions ── */
  fetchImpl = connsHandler();
  openConnectionManager();
  await tick();
  const host = registry["ws-conn-mgr"];
  ok(!host.classList.contains("hidden"), "D: manager opened");
  const card = host.children[0];
  eq(card.children[0].children[0].textContent, "AI Connections", "D: title");
  const list = card.children[1];
  const items = list.children.filter((c) => c.className === "ws-conn-item");
  eq(items.length, 2, "D: one card per connection");
  ok(/OpenAI Primary/.test(items[0].children[0].children[0].textContent), "D: display name");
  ok(/openai/.test(items[0].children[1].textContent), "D: provider + status shown");
  const actionButtons = items[0].children[2].children.map((b) => b.textContent);
  eq(JSON.stringify(actionButtons), '["Validate","Edit","Delete"]', "D: actions");

  /* ── E: edit never displays a stored secret ── */
  const editBtn = items[0].children[2].children[1];
  editBtn.dispatch("click");
  const formHost = card.children[2];
  const form = formHost.children[0];
  ok(form.className.includes("editing"), "E: edit form opened");
  const keyRow = form.children[6];
  const masked = keyRow.children[2];
  ok(/configured/.test(masked.textContent), "E: masked marker, not the secret");
  ok(!/test-secret-value/.test(masked.textContent), "E: secret never rendered");
  ok(!/sk-|secret/.test(masked.textContent), "E: no key-like text rendered");
  const keyInput = keyRow.children[1];
  eq(keyInput.type, "password", "E: key input is a password field");

  /* ── F: the secret value never appears in any DOM text or JS state ── */
  function domText(node, acc) {
    acc = acc || [];
    if (typeof node.textContent === "string" && node.textContent) acc.push(node.textContent);
    (node.children || []).forEach((c) => domText(c, acc));
    return acc;
  }
  ok(!domText(host).some((t) => t.includes(SECRET)), "F: secret not in DOM");
  ok(!JSON.stringify(S).includes(SECRET), "F: secret not in S state");
  ok(!requests.some((r) => JSON.stringify(r).includes(SECRET)),
     "F: secret never sent in a request (it is only sent on save)");

  /* ── G: create/update/delete flow through the API ── */
  // create: fill the add form and save
  const CONNECTIONS_WITH_NEW = CONNECTIONS.concat([{
    id: "conn_openai_2", connection_id: "conn_openai_2", provider: "openai",
    display_name: "OpenAI Secondary", credential_type: "api_key",
    endpoint: "", deployment: "", status: "configured", default: false }]);
  fetchImpl = (p, opts) => {
    if (p === "/api/connections" && (!opts || !opts.method || opts.method === "GET")) {
      return jsonRes(200, { connections: CONNECTIONS_WITH_NEW, providers: PROVIDERS });
    }
    if (p === "/api/connections" && opts && opts.method === "POST") {
      return jsonRes(200, { connection: CONNECTIONS_WITH_NEW[2] });
    }
    if (p === "/api/connections/conn_openai_2/validate") {
      return jsonRes(200, { ok: true, detail: "validated" });
    }
    if (p === "/api/connections/conn_openai_2" && opts && opts.method === "DELETE") {
      return jsonRes(200, { ok: true });
    }
    throw new Error("unexpected fetch: " + p);
  };
  await renderConnectionManager();
  await tick();
  const card2 = host.children[0];
  const addForm = card2.children[2].children[0];
  ok(!addForm.className.includes("editing"), "G: add form shown by default");
  const addSel = addForm.children[1].children[1];
  addSel.value = "openai";
  addSel.dispatch("change");
  const nameInput = addForm.children[3].children[1];
  nameInput.value = "OpenAI Secondary";
  const keyRowAdd = addForm.children[6];
  keyRowAdd.children[1].value = SECRET;
  addForm.children[7].children[0].dispatch("click");
  await tick();
  const createReq = requests.find((r) => r.path === "/api/connections" && r.opts && r.opts.method === "POST");
  ok(createReq, "G: create request issued");
  const createBody = JSON.parse(createReq.opts.body);
  eq(createBody.provider, "openai", "G: provider sent");
  eq(createBody.display_name, "OpenAI Secondary", "G: display name sent");
  eq(createBody.api_key, SECRET, "G: key sent once on create (backend stores it)");
  ok(!JSON.stringify(createBody).includes("authorization"), "G: no auth header field");

  // validate via the card action
  await renderConnectionManager();
  await tick();
  function cardFor(id) {
    return host.children[0].children[1].children.find(
      (c) => c.className === "ws-conn-item"
        && c.children[0].children.some((s) => s.className === "ws-conn-item-id" && s.textContent === id));
  }
  const validateBtn = cardFor("conn_openai_2").children[2].children[0];
  validateBtn.dispatch("click");
  await tick();
  ok(requests.some((r) => r.path === "/api/connections/conn_openai_2/validate"),
     "G: validate request issued");

  // delete via the card action
  await renderConnectionManager();
  await tick();
  const delBtn = cardFor("conn_openai_2").children[2].children[2];
  delBtn.dispatch("click");
  await tick();
  ok(CONFIRMS.length >= 1, "G: delete asks for confirmation");
  ok(requests.some((r) => r.path === "/api/connections/conn_openai_2" && r.opts && r.opts.method === "DELETE"),
     "G: delete request issued");

  console.log("workspace connections tests passed:", count);
}

main().catch((err) => { console.error(err); process.exit(1); });

/* ─────────────────────────────────────────────────────────────────────
   workspace.js — Agent Workspace / visual workflow designer.
   Vanilla JS, no build step. Every mutation flows through the REST API
   (/api/workflows/*) backed by scripts.core.workflows + workflow_engine.

   Model independence: a node references an agent key, an optional runtime
   model override, and role ids — never editing AgentSpec, roles.json or
   opencode.json. API keys never leave the backend.
   ───────────────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function empty(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      let detail = data && data.detail;
      if (typeof detail !== "string") detail = JSON.stringify(detail);
      throw Object.assign(new Error(detail || res.statusText), { status: res.status, data });
    }
    return data;
  }
  function post(path, body) {
    return api(path, { method: "POST", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify(body || {}) });
  }
  function put(path, body) {
    return api(path, { method: "PUT", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify(body || {}) });
  }
  function del(path) { return api(path, { method: "DELETE" }); }

  const ORIGIN = 2000;               // world offset so nodes can sit near zero
  const WORLD = 4000;                // SVG size
  const SVGN = "http://www.w3.org/2000/svg";

  /* ── state ─────────────────────────────────────────────────────── */
  const S = {
    workflow: { id: "untitled", name: "", project: "", nodes: [], edges: [], entry: [], state: {}, settings: { max_iterations: 3 } },
    agents: [],            // [{tag,name,agent,model}]
    roles: [],             // [{id,name,...}]
    roleAssignments: {},   // {agentKey: [roleIds]}
    models: [],            // [{id,name}] available models
    modelCatalog: [],      // Phase 3 model-registry catalog [{id,provider,...}]
    modelById: {},         // {id: ModelSpec} quick lookup
    prompts: [],           // prompt-profile metadata from /api/prompts
    promptById: {},        // {id: meta} quick lookup
    promptTexts: {},       // {id: full prompt text} cache (fetched on demand)
    taskRecs: {},          // {nodeId: [recommendation]} transient (not persisted)
    dirty: false,
    selected: { type: null, id: null },   // 'node' | 'edge'
    runId: null,
    activeWorkflowId: null, // the id /api/active-workflow reports as active
    agentFilter: "",        // live library search query
    runStatuses: {},        // {nodeId: status} from the active run (empty when idle)
    waves: {},              // {nodeId: waveIndex} from the last dry-run preview
    zoom: 1,
    tx: 0, ty: 0,
    nid: 0,
  };

  const STATE_LABEL = {
    ready: "Ready", waiting: "Waiting", running: "Running",
    completed: "Completed", failed: "Failed", skipped: "Skipped",
    disabled: "Disabled", terminal: "Terminal",
  };

  const TEMPLATE_LABELS = {
    sequential: "Sequential Pipeline",
    parallel: "Parallel Engineering",
    "planner-workers-reviewer": "Planner / Workers / Reviewer",
    reflection: "Developer / Reviewer / Retry",
    "parallel-specialists": "Parallel Specialists",
    "research-analysis-writer": "Research / Analysis / Writer",
    supervisor: "Supervisor",
    router: "Router",
    hierarchical: "Hierarchical",
    empty: "Empty Workflow",
  };

  function nodeState(n) {
    if (!n.enabled) return "disabled";
    if (n.kind === "end") return S.runStatuses[n.id] || "terminal";
    return S.runStatuses[n.id] || "ready";
  }

  function nextId() { S.nid += 1; return "n" + S.nid; }

  function recalcNid() {
    // Recompute the node-id counter from the current graph so a freshly added
    // node never collides with an existing id. Templates use semantic slugs
    // ("architect", "developer", …) while user nodes use n1..nN; scan every
    // id for the largest numeric suffix and keep at least the node count.
    let max = S.workflow.nodes.length;
    (S.workflow.nodes || []).forEach((n) => {
      const m = /^n(\d+)$/.exec(n.id || "");
      if (m) max = Math.max(max, parseInt(m[1], 10));
    });
    S.nid = max;
  }
  function nodeById(id) { return S.workflow.nodes.find((n) => n.id === id); }
  function edgeKey(e) { return e.source + "|" + e.target; }
  function edgeByKey(key) { return S.workflow.edges.find((e) => edgeKey(e) === key); }
  function agentByKey(key) { return S.agents.find((a) => a.agent === key); }
  function roleName(id) { const r = S.roles.find((x) => x.id === id); return r ? (r.name || r.id) : id; }

  /* ── prompt library (role-typed prompt profiles) ─────────────────
     A node may reference a Prompt Profile (``prompt_profile`` id) as the
     *source* of its editable Instruction. The mapping below mirrors
     ``scripts.core.prompt_library.registry`` (deterministic keyword match,
     no LLM) so the dropdown can suggest profiles for the node's role/agent. */
  function promptRoleKey(value) {
    return (value || "").toLowerCase().replace(/_/g, " ").replace(/-/g, " ")
      .replace(/\s+/g, " ").trim();
  }

  const PROMPT_ROLES = ["software_engineer", "software_architect", "code_reviewer",
    "debugger", "qa_engineer", "security_engineer", "devops_engineer",
    "cloud_engineer", "data_engineer", "ai_engineer", "researcher",
    "technical_writer", "project_manager", "orchestrator"];
  const PROMPT_ROLE_IDS = {};
  PROMPT_ROLES.forEach((r) => { PROMPT_ROLE_IDS[promptRoleKey(r)] = r; });

  // keyword → prompt role, most-specific first (mirrors registry.py _KEYWORDS)
  const PROMPT_ROLE_ALIASES = [
    ["software_architect", ["architect", "architecture"]],
    ["code_reviewer", ["review", "reviewer"]],
    ["debugger", ["debug"]],
    ["qa_engineer", ["qa", "test", "testing", "quality", "e2e"]],
    ["security_engineer", ["security", "secure", "threat", "audit"]],
    ["devops_engineer", ["devops", "cicd", "ci/cd", "ci cd", "deploy", "infrastructure", "release"]],
    ["cloud_engineer", ["cloud", "azure", "aws", "gcp", "networking", "network"]],
    ["data_engineer", ["data", "etl", "pipeline", "warehouse"]],
    ["ai_engineer", ["ai", "llm", "agent", "rag", "machine learning", "ml"]],
    ["researcher", ["research", "researcher", "analyst", "literature"]],
    ["technical_writer", ["writer", "documentation", "docs", "write"]],
    ["project_manager", ["manager", "project", "pm", "planning", "delivery", "risk"]],
    ["orchestrator", ["orchestrat", "coordinator", "workflow", "delegat"]],
    ["software_engineer", ["developer", "engineer", "software", "coding", "code", "python", "fastapi"]],
  ];

  function suggestPromptRole(key) {
    const k = promptRoleKey(key);
    if (!k) return null;
    if (PROMPT_ROLE_IDS[k]) return PROMPT_ROLE_IDS[k];
    for (const [role, words] of PROMPT_ROLE_ALIASES) {
      if (words.some((w) => k.indexOf(w) !== -1)) return role;
    }
    return null;
  }

  function nodePromptRoleKeys(n) {
    const keys = [];
    (n.roles || []).forEach((r) => keys.push(r));
    if (!keys.length && S.roleAssignments && S.roleAssignments[n.agent]) {
      (S.roleAssignments[n.agent] || []).forEach((r) => keys.push(r));
    }
    if (!keys.length) keys.push(n.agent);
    return keys;
  }

  function suggestPromptsForNode(n) {
    const roles = new Set();
    nodePromptRoleKeys(n).forEach((k) => {
      const r = suggestPromptRole(k);
      if (r) roles.add(r);
    });
    if (!roles.size) return [];
    return S.prompts.filter((p) => roles.has(p.role));
  }

  async function fetchPromptText(id) {
    if (!id) return "";
    if (S.promptTexts[id]) return S.promptTexts[id];
    try {
      const r = await api(`/api/prompts/${encodeURIComponent(id)}`);
      S.promptTexts[id] = (r.prompt && r.prompt.prompt) || "";
      return S.promptTexts[id];
    } catch (_) { return ""; }
  }

  async function applyPromptToNode(n, id) {
    const text = await fetchPromptText(id);
    if (text) { n.instructions = text; markDirty(); }
    return text;
  }

  async function onPromptSelected(n, id) {
    n.prompt_profile = id;
    markDirty();
    // Safe application: only auto-fill the Instruction when it is empty — a
    // custom instruction is never silently overwritten (the Apply button does that).
    if (id && !(n.instructions || "").trim()) {
      await applyPromptToNode(n, id);
    }
    return n;
  }

  /* ── Task → Prompt recommendation (Phase 2, deterministic) ────────
     "Suggest Prompt" inspects the node's Task/Purpose text + role and asks the
     backend to rank prompt profiles (keyword/capability matching — no LLM). The
     classification is persisted on the node (``n.task``); the ranked list is
     transient (``S.taskRecs``). Applying a recommendation never changes the
     user's model. */
  function nodeTaskDescription(n) {
    return ((n.task && (n.task.description || n.task.context)) || "").trim();
  }

  function nodePromptRole(n) {
    for (const k of nodePromptRoleKeys(n)) {
      const r = suggestPromptRole(k);
      if (r) return r;
    }
    return null;
  }

  async function suggestPrompt(n) {
    const desc = nodeTaskDescription(n);
    if (!desc) { setError("enter a Task / Purpose description first"); return null; }
    try {
      const r = await post("/api/prompts/recommend", {
        task: desc,
        role: nodePromptRole(n),
      });
      // Persist the classification on the node (optional metadata); keep the
      // ranked list transient for display.
      n.task = Object.assign({}, n.task || {}, r.task || {}, { description: desc });
      S.taskRecs[n.id] = r.recommendations || [];
      markDirty();
      renderProps();
      return S.taskRecs[n.id];
    } catch (err) { setError(err.message); return null; }
  }

  function renderRecommendationPreview(body, n) {
    const recs = S.taskRecs[n.id] || [];
    if (!recs.length) return;
    const wrap = el("div", "ws-recs");
    wrap.appendChild(el("div", "ws-recs-title", "Recommended Prompt"));
    recs.forEach((r) => {
      const p = S.promptById[r.prompt_id];
      const item = el("button", "ws-rec-item"
        + (n.prompt_profile === r.prompt_id ? " selected" : ""));
      item.type = "button";
      item.appendChild(el("span", "ws-rec-name", p ? p.name : r.prompt_id));
      item.appendChild(el("span", "ws-rec-score", Math.round(r.score * 100) + "% match"));
      item.title = (r.reason || "") + " — deterministic matching score (not AI confidence)";
      item.addEventListener("click", async () => {
        await onPromptSelected(n, r.prompt_id);
        renderProps();
      });
      wrap.appendChild(item);
    });
    wrap.appendChild(el("div", "ws-recs-note",
      "Percentages are deterministic matching scores, not AI confidence."));
    body.appendChild(wrap);
  }

  function renderModelCapabilityPreview(body, n) {
    const p = S.promptById[n.prompt_profile];
    if (!p || !p.model_preferences) return;
    const wrap = el("div", "ws-model-prefs");
    wrap.appendChild(el("div", "ws-model-prefs-title", "Model requirements"));
    const labels = { reasoning: "Reasoning", coding: "Coding", tool_use: "Tool use",
                     context: "Context", latency: "Latency", cost: "Cost" };
    const table = el("div", "ws-model-prefs-table");
    Object.keys(labels).forEach((k) => {
      const row = el("div", "ws-model-pref-row");
      row.appendChild(el("span", "ws-model-pref-label", labels[k]));
      const val = String(p.model_preferences[k] || "");
      row.appendChild(el("span", "ws-model-pref-value",
        val ? val.charAt(0).toUpperCase() + val.slice(1) : "—"));
      table.appendChild(row);
    });
    wrap.appendChild(table);
    body.appendChild(wrap);
  }

  /* ── Phase 3: Model Registry catalog + selection preview ─────────
     The registry is metadata-only (no provider SDKs, no keys, no calls).
     Recommendations come from POST /api/models/recommend (deterministic
     matching). An explicitly chosen model is always preserved: it is listed
     first and flagged, never overwritten by a recommendation. */
  async function loadModelCatalog() {
    try {
      const r = await api("/api/models");
      S.modelCatalog = r.models || [];
      S.modelById = {};
      S.modelCatalog.forEach((m) => { S.modelById[m.id] = m; });
    } catch (_) {
      S.modelCatalog = [];
      S.modelById = {};
    }
  }

  function modelProviderOptions() {
    const set = new Set();
    (S.modelCatalog || []).forEach((m) => { if (m.provider) set.add(m.provider); });
    return Array.from(set).sort();
  }

  function modelCapability(m, key) {
    const c = (m && m.capabilities) || {};
    const v = c[key];
    return v ? String(v).charAt(0).toUpperCase() + String(v).slice(1) : "—";
  }

  function modelDisplayName(id) {
    const m = S.modelById[id];
    return m ? (m.display_name || id) : id;
  }

  function renderModelRecommendation(body, n) {
    const wrap = el("div", "ws-model-recs");
    wrap.appendChild(el("div", "ws-model-recs-title", "Recommended Models"));
    const provSel = el("select", "ws-model-provider");
    const all = el("option", null, "All providers");
    all.value = "";
    provSel.appendChild(all);
    modelProviderOptions().forEach((p) => {
      const o = el("option", null, p);
      o.value = p;
      provSel.appendChild(o);
    });
    const listEl = el("div", "ws-model-recs-list");
    wrap.appendChild(provSel);
    wrap.appendChild(listEl);
    body.appendChild(wrap);

    async function refresh() {
      empty(listEl);
      const hint = el("div", "ws-model-recs-hint", "…");
      listEl.appendChild(hint);
      let bodyJson;
      try {
        bodyJson = await post("/api/models/recommend", {
          task: nodeTaskDescription(n) || undefined,
          prompt_profile: n.prompt_profile || undefined,
          provider: provSel.value || undefined,
          explicit_model: n.model || undefined,
        });
      } catch (_) {
        empty(listEl);
        listEl.appendChild(el("div", "ws-model-recs-hint",
          "model recommendation unavailable"));
        return;
      }
      const recs = bodyJson.recommendations || [];
      empty(listEl);
      if (!recs.length) {
        listEl.appendChild(el("div", "ws-model-recs-hint",
          "no catalog match — set a task/prompt profile for recommendations"));
        return;
      }
      recs.forEach((rec) => {
        const item = el("div", "ws-model-rec-item"
          + (rec.explicit ? " explicit" : "")
          + (n.model === rec.model_id ? " selected" : ""));
        const top = el("div", "ws-model-rec-top");
        top.appendChild(el("span", "ws-model-rec-name", modelDisplayName(rec.model_id)));
        top.appendChild(el("span", "ws-model-rec-score",
          Math.round(rec.score * 100) + "% match"));
        item.appendChild(top);
        if (rec.reason) {
          item.appendChild(el("div", "ws-model-rec-reason", rec.reason));
        }
        if (rec.explicit) {
          item.appendChild(el("div", "ws-model-rec-note",
            "explicit selection — always preserved"));
        } else if (n.model !== rec.model_id) {
          const apply = el("button", "btn ws-model-rec-apply", "Apply");
          apply.type = "button";
          apply.addEventListener("click", () => {
            n.model = rec.model_id;      // user-initiated: the workflow carries it
            markDirty();
            renderNodes();
            renderProps();
          });
          item.appendChild(apply);
        } else {
          item.appendChild(el("div", "ws-model-rec-note", "selected"));
        }
        listEl.appendChild(item);
      });
      if (!n.model) {
        listEl.appendChild(el("div", "ws-model-recs-hint",
          "Auto will use: " + modelDisplayName(recs[0].model_id) +
          " (" + Math.round(recs[0].score * 100) + "%)"));
      }
    }
    provSel.addEventListener("change", refresh);
    refresh();
  }

  function renderModelDetails(body, n) {
    if (!n.model) return;
    const m = S.modelById[n.model];
    if (!m) return;
    const wrap = el("div", "ws-model-details");
    wrap.appendChild(el("div", "ws-model-details-title", "Model details"));
    const rows = [
      ["Provider", m.provider],
      ["Family", m.family],
      ["Context", m.context_window ? m.context_window.toLocaleString() + " tokens" : ""],
      ["Reasoning", modelCapability(m, "reasoning")],
      ["Coding", modelCapability(m, "coding")],
      ["Tool use", modelCapability(m, "tool_use")],
      ["Vision", modelCapability(m, "vision")],
      ["Structured output", modelCapability(m, "structured_output")],
      ["Latency", modelCapability(m, "latency")],
      ["Cost tier", modelCapability(m, "cost")],
    ];
    rows.forEach(([k, v]) => {
      if (!v) return;
      const row = el("div", "ws-model-details-row");
      row.appendChild(el("span", "ws-model-details-label", k));
      row.appendChild(el("span", "ws-model-details-value", String(v)));
      wrap.appendChild(row);
    });
    body.appendChild(wrap);
  }

  /* ── meta loading ─────────────────────────────────────────────── */
  async function loadMeta() {
    try {
      const ag = await api("/api/agents");
      S.agents = ag.agents || [];
    } catch (_) { /* keep empty */ }
    try {
      const r = await api("/api/settings/roles");
      S.roles = r.roles || [];
      S.roleAssignments = r.assignments || {};
    } catch (_) { /* keep empty */ }
    try {
      const m = await api("/api/settings/models");
      S.models = m.available || [];
    } catch (_) { /* keep empty */ }
    try {
      const pr = await api("/api/prompts");
      S.prompts = pr.prompts || [];
      S.promptById = {};
      S.prompts.forEach((p) => { S.promptById[p.id] = p; });
    } catch (_) { /* keep empty */ }
    await loadModelCatalog();
    renderLibrary();
  }

  function allModelOptions() {
    // every model the picker may offer: catalog models + the agents' resolved
    // models + any model already used by a node (preserves custom entries).
    const opts = new Map();
    S.models.forEach((m) => opts.set(m.id, m.name || m.id));
    S.agents.forEach((a) => { if (a.model) opts.set(a.model, a.model); });
    S.workflow.nodes.forEach((n) => { if (n.model) opts.set(n.model, n.model); });
    return opts;
  }

  /* ── model picker (searchable combobox) ──────────────────────────
     A node's model is an optional per-instance override:
       "" (empty)   → Auto / runtime default (resolved from opencode.json)
       provider/id  → explicit override for this node only.
     Selecting a model writes straight into the node (so the workflow payload
     carries it) and re-renders the node card so the display never lags. */
  function modelCombo(node) {
    const opts = allModelOptions();
    const box = el("div", "combo ws-model-combo");
    const trigger = el("button", "combo-trigger");
    trigger.type = "button";
    const label = el("span", "combo-value");
    const caret = el("span", "combo-caret", "▾");
    trigger.appendChild(label);
    trigger.appendChild(caret);
    box.appendChild(trigger);

    const list = el("div", "combo-list hidden");
    const search = el("input", "combo-search");
    search.placeholder = "type to filter (provider / model)…";
    search.autocomplete = "off";
    list.appendChild(search);
    const items = el("div", "combo-items");
    list.appendChild(items);
    box.appendChild(list);

    const AUTO = ["", "Auto / runtime default"];
    const entries = Array.from(opts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    let value = node.model || "";
    let filteredEntries = entries.slice();
    let highlight = -1;

    function updateLabel() {
      label.classList.toggle("combo-auto", !value);
      label.textContent = value ? (opts.get(value) || value) : AUTO[1];
      const a = agentByKey(node.agent);
      trigger.title = value
        ? `explicit model: ${value}`
        : (a && a.model ? `Auto → resolves to ${a.model} (agent default)` : AUTO[1]);
    }
    updateLabel();

    function renderItems() {
      empty(items);
      const visible = [AUTO].concat(filteredEntries);
      visible.forEach(([id, name], i) => {
        const item = el("div", "combo-item"
          + (i === highlight ? " active" : "")
          + (id === value ? " selected" : ""), name);
        item.dataset.id = id;
        item.addEventListener("mousedown", (e) => { e.preventDefault(); choose(id); });
        items.appendChild(item);
      });
      const custom = el("div", "combo-item combo-custom", "custom provider / model…");
      custom.addEventListener("mousedown", (e) => { e.preventDefault(); chooseCustom(); });
      items.appendChild(custom);
    }

    function filter(q) {
      const needle = q.trim().toLowerCase();
      filteredEntries = needle
        ? entries.filter(([id, name]) =>
            id.toLowerCase().includes(needle) || name.toLowerCase().includes(needle))
        : entries.slice();
      highlight = -1;
      renderItems();
    }

    function open() {
      list.classList.remove("hidden");
      search.value = "";
      filteredEntries = entries.slice();
      highlight = -1;
      renderItems();
      search.focus();
    }

    function close() {
      list.classList.add("hidden");
      search.value = "";
    }

    function commit(id) {
      value = id || "";
      node.model = value;               // persist into the workflow node
      updateLabel();
      close();
      markDirty();
      renderNodes();                    // update the node card immediately
    }

    function choose(id) { commit(id); }

    function chooseCustom() {
      close();
      const typed = window.prompt("Model id (provider/model):", value || "");
      if (typed === null) return;
      commit(typed.trim());
    }

    trigger.addEventListener("click", () => {
      if (list.classList.contains("hidden")) open();
      else close();
    });

    search.addEventListener("input", () => filter(search.value));
    search.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!filteredEntries.length) return;
        highlight = highlight < 0 ? 0
          : Math.min(highlight + 1, filteredEntries.length);   // +1 for the Auto row
        renderItems();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (!filteredEntries.length) return;
        highlight = highlight < 0 ? filteredEntries.length
          : Math.max(highlight - 1, 0);
        renderItems();
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        const q = search.value.trim();
        if (highlight >= 0 && highlight <= filteredEntries.length) {
          const target = highlight === 0 ? AUTO : filteredEntries[highlight - 1];
          choose(target[0]);
        } else if (filteredEntries.length === 1) {
          choose(filteredEntries[0][0]);
        } else if (q && q.includes("/")) {
          commit(q);                   // free-text provider/model id
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close();
      }
    });

    return box;
  }

  /* ── library ──────────────────────────────────────────────────── */
  function matchingAgents() {
    const q = (S.agentFilter || "").trim().toLowerCase();
    if (!q) return S.agents.slice();
    return S.agents.filter((a) =>
      a.name.toLowerCase().includes(q) ||
      a.tag.toLowerCase().includes(q) ||
      a.agent.toLowerCase().includes(q) ||
      (a.model && a.model.toLowerCase().includes(q)));
  }

  function renderLibrary() {
    const list = $("#ws-library-list");
    empty(list);
    if (!S.agents.length) {
      list.appendChild(el("div", "placeholder", "no agents"));
      return;
    }
    const agents = matchingAgents();
    if (!agents.length) {
      list.appendChild(el("div", "placeholder", "no matching agents"));
      return;
    }
    agents.forEach((a) => {
      const card = el("button", "ws-lib-agent");
      card.type = "button";
      card.draggable = true;
      card.appendChild(el("span", "ws-lib-name", `${a.tag.toUpperCase()} · ${a.name}`));
      card.appendChild(el("span", "ws-lib-model", a.model || "Auto"));
      const roles = (S.roleAssignments[a.agent] || []).map(roleName).join(", ");
      if (roles) card.appendChild(el("span", "ws-lib-roles", roles));
      card.title = "Add an instance of this agent to the canvas (click or drag)";
      card.addEventListener("click", () => addNode(a));
      card.addEventListener("dragstart", (e) => {
        if (e.dataTransfer) {
          e.dataTransfer.setData(AGENT_DRAG_TYPE, a.agent);   // agent key only
          e.dataTransfer.effectAllowed = "copy";
        }
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => card.classList.remove("dragging"));
      list.appendChild(card);
    });
  }

  /* ── library → canvas drag & drop (HTML5) ──────────────────────
     The library uses the native drag/drop event chain (dragstart → dragover
     → drop → dragend) to create a node at the drop point; existing node
     move/connect stays on pointer events — the two systems never mix. Only
     the agent key travels in the drag payload (never a model/credential). */
  const AGENT_DRAG_TYPE = "application/x-zova-agent";

  function bindDragDrop() {
    const canvas = $("#ws-canvas");
    if (!canvas) return;
    canvas.addEventListener("dragover", (e) => {
      e.preventDefault();                       // allow drop
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      canvas.classList.add("drag-over");
    });
    canvas.addEventListener("dragleave", () => canvas.classList.remove("drag-over"));
    canvas.addEventListener("drop", (e) => {
      e.preventDefault();
      canvas.classList.remove("drag-over");
      const key = e.dataTransfer && typeof e.dataTransfer.getData === "function"
        ? e.dataTransfer.getData(AGENT_DRAG_TYPE) : "";
      if (!key) return;
      const agent = S.agents.find((a) => a.agent === key);
      if (!agent) return;
      const p = canvasPos(e);                   // client → world coordinates
      addNode(agent, { x: p.x, y: p.y });
    });
    canvas.addEventListener("dragend", () => canvas.classList.remove("drag-over"));
  }

  function addNode(agent, pos) {
    const count = S.workflow.nodes.filter((n) => n.agent === agent.agent).length;
    const n = {
      id: nextId(), label: `${agent.name}${count ? " #" + (count + 1) : ""}`,
      agent: agent.agent, kind: "agent", model: "",
      roles: [], instructions: "", tools: [], enabled: true,
      x: (pos && Number.isFinite(pos.x)) ? pos.x : 120 + (S.workflow.nodes.length % 4) * 160,
      y: (pos && Number.isFinite(pos.y)) ? pos.y : 120 + (S.workflow.nodes.length % 3) * 140,
    };
    S.workflow.nodes.push(n);
    markDirty();
    render();
    select("node", n.id);
    return n;
  }

  /* ── rendering ────────────────────────────────────────────────── */
  function worldTransform() {
    return `translate(${S.tx}px,${S.ty}px) scale(${S.zoom})`;
  }

  function render() {
    $("#ws-world").style.transform = worldTransform();
    renderEdges();
    renderNodes();
    renderEmptyHint();
    updateTitle();
    updateActivateButton();
  }

  function renderEmptyHint() {
    const hint = $("#ws-empty-hint");
    if (hint) hint.classList.toggle("hidden", S.workflow.nodes.length > 0);
  }

  function renderNodes() {
    const host = $("#ws-nodes");
    empty(host);
    S.workflow.nodes.forEach((n) => {
      const card = el("div", "wf-node" + (S.selected.type === "node" && S.selected.id === n.id ? " selected" : "") + (n.enabled ? "" : " disabled"));
      card.dataset.id = n.id;
      card.style.left = (n.x + ORIGIN) + "px";
      card.style.top = (n.y + ORIGIN) + "px";

      card.appendChild(el("div", "wf-in", "◉"));
      const body = el("div", "wf-node-body");
      const head = el("div", "wf-node-head");
      const st = nodeState(n);
      const dot = el("span", "wf-node-dot st-" + st);
      head.appendChild(dot);
      if (n.kind === "end") head.appendChild(el("span", "wf-node-kind", "end"));
      head.appendChild(el("span", "wf-node-label", n.label || n.agent || "(node)"));
      body.appendChild(head);
      if (n.kind === "agent") {
        const a = agentByKey(n.agent);
        if (a) body.appendChild(el("div", "wf-node-agent", a.name));
      }
      const sub = el("div", "wf-node-sub");
      if (n.kind === "end") {
        sub.textContent = "terminal";
      } else {
        sub.textContent = n.model || "Auto / runtime default";
        const a = agentByKey(n.agent);
        sub.title = n.model
          ? `explicit model: ${n.model}`
          : (a && a.model ? `Auto → ${a.model}` : "Auto / runtime default");
      }
      body.appendChild(sub);
      const rolesLine = n.roles && n.roles.length ? n.roles.map(roleName).join(", ") : "";
      if (rolesLine) body.appendChild(el("div", "wf-node-roles", rolesLine));
      body.appendChild(el("div", "wf-node-state", STATE_LABEL[st] || "Ready"));
      if (S.waves[n.id]) body.appendChild(el("span", "wf-node-wave", "wave " + S.waves[n.id]));
      card.appendChild(body);
      card.appendChild(el("div", "wf-out", "◉"));

      card.addEventListener("pointerdown", (e) => onNodePointerDown(e, n.id));
      card.addEventListener("click", (e) => { e.stopPropagation(); select("node", n.id); });
      host.appendChild(card);
    });
    applyRunStatuses();
  }

  function renderEdges() {
    const svg = $("#ws-edges");
    empty(svg);
    svg.setAttribute("viewBox", `0 0 ${WORLD} ${WORLD}`);
    svg.setAttribute("width", WORLD);
    svg.setAttribute("height", WORLD);

    // arrowhead marker
    const defs = document.createElementNS(SVGN, "defs");
    const marker = document.createElementNS(SVGN, "marker");
    marker.setAttribute("id", "ws-arrow");
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", 8); marker.setAttribute("refY", 5);
    marker.setAttribute("markerWidth", 7); marker.setAttribute("markerHeight", 7);
    marker.setAttribute("orient", "auto-start-reverse");
    const path = document.createElementNS(SVGN, "path");
    path.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
    path.setAttribute("fill", "var(--text-muted)");
    marker.appendChild(path);
    defs.appendChild(marker);
    svg.appendChild(defs);

    S.workflow.edges.forEach((e) => {
      const a = nodeById(e.source), b = nodeById(e.target);
      if (!a || !b) return;
      const key = edgeKey(e);
      const grp = document.createElementNS(SVGN, "g");
      grp.setAttribute("class", "ws-edge" + (S.selected.type === "edge" && S.selected.id === key ? " selected" : ""));
      grp.dataset.key = key;
      const line = document.createElementNS(SVGN, "line");
      line.setAttribute("x1", a.x + ORIGIN); line.setAttribute("y1", a.y + ORIGIN);
      line.setAttribute("x2", b.x + ORIGIN); line.setAttribute("y2", b.y + ORIGIN);
      line.setAttribute("marker-end", "url(#ws-arrow)");
      grp.appendChild(line);
      if (e.condition) {
        const label = document.createElementNS(SVGN, "text");
        label.setAttribute("x", (a.x + b.x) / 2 + ORIGIN);
        label.setAttribute("y", (a.y + b.y) / 2 + ORIGIN - 6);
        label.setAttribute("class", "ws-edge-label");
        label.textContent = e.condition;
        grp.appendChild(label);
      }
      // wide hit area for click selection
      const hit = document.createElementNS(SVGN, "line");
      hit.setAttribute("class", "ws-edge-hit");
      hit.setAttribute("x1", a.x + ORIGIN); hit.setAttribute("y1", a.y + ORIGIN);
      hit.setAttribute("x2", b.x + ORIGIN); hit.setAttribute("y2", b.y + ORIGIN);
      grp.appendChild(hit);
      grp.addEventListener("click", (ev) => { ev.stopPropagation(); select("edge", key); });
      svg.appendChild(grp);
    });
  }

  function updateTitle() {
    document.title = (S.workflow.name || S.workflow.id) + " · Agent Workspace";
    $("#ws-status").textContent = `${S.workflow.nodes.length} nodes · ${S.workflow.edges.length} edges`;
  }

  function fitToScreen() {
    const nodes = S.workflow.nodes;
    if (!nodes.length) { S.zoom = 1; S.tx = 0; S.ty = 0; render(); return; }
    const canvas = $("#ws-canvas");
    const cw = canvas.clientWidth || 800;
    const ch = canvas.clientHeight || 600;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach((n) => {
      minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y);
    });
    const w = Math.max(1, maxX - minX + 240);   // padding for node size + labels
    const h = Math.max(1, maxY - minY + 200);
    S.zoom = Math.min(1.5, Math.max(0.4, Math.min(cw / w, ch / h)));
    const cx = ((minX + maxX) / 2) + ORIGIN;
    const cy = ((minY + maxY) / 2) + ORIGIN;
    S.tx = cw / 2 - cx * S.zoom;
    S.ty = ch / 2 - cy * S.zoom;
    render();
  }

  /* ── selection ────────────────────────────────────────────────── */
  function select(type, id) {
    S.selected = { type, id };
    renderNodes();
    renderEdges();
    renderProps();
  }

  function markDirty() {
    S.dirty = true;
    $("#ws-dirty").classList.remove("hidden");
  }
  function markClean() {
    S.dirty = false;
    $("#ws-dirty").classList.add("hidden");
  }

  /* ── node drag + connect ──────────────────────────────────────── */
  let drag = null;   // {type:'move'|'connect', id, sx, sy, nx, ny, temp}
  function canvasPos(e) {
    const r = $("#ws-canvas").getBoundingClientRect();
    // client → world: undo the canvas offset, the pan, and the zoom, then
    // subtract ORIGIN. node.x is a *world* coordinate centred near zero; every
    // renderer (renderNodes, edges, fitToScreen) shifts it into the 0..WORLD
    // layer space by adding ORIGIN, so the inverse must subtract it here or
    // dropped/dragged nodes land ORIGIN*zoom px away from the pointer.
    return { x: (e.clientX - r.left - S.tx) / S.zoom - ORIGIN, y: (e.clientY - r.top - S.ty) / S.zoom - ORIGIN };
  }

  function onNodePointerDown(e, id) {
    if (e.button !== 0) return;
    const node = nodeById(id);
    const target = e.target;
    if (target.closest(".wf-out")) {
      // start a connection
      e.preventDefault();
      e.stopPropagation();
      const p = canvasPos(e);
      drag = { type: "connect", id, temp: tempEdge(node.x, node.y, p.x, p.y) };
      window.addEventListener("pointermove", onConnectMove);
      window.addEventListener("pointerup", onConnectUp);
    } else if (!target.closest(".wf-in")) {
      // move node
      e.preventDefault();
      const p = canvasPos(e);
      drag = { type: "move", id, dx: p.x - node.x, dy: p.y - node.y };
      window.addEventListener("pointermove", onNodeMove);
      window.addEventListener("pointerup", onNodeUp);
    }
  }

  function onNodeMove(e) {
    if (!drag || drag.type !== "move") return;
    const p = canvasPos(e);
    const node = nodeById(drag.id);
    node.x = p.x - drag.dx;
    node.y = p.y - drag.dy;
    const card = $(`.wf-node[data-id="${drag.id}"]`);
    if (card) { card.style.left = (node.x + ORIGIN) + "px"; card.style.top = (node.y + ORIGIN) + "px"; }
    renderEdges();
    markDirty();
  }
  function onNodeUp() {
    if (drag && drag.type === "move") { drag = null; }
    window.removeEventListener("pointermove", onNodeMove);
    window.removeEventListener("pointerup", onNodeUp);
  }

  function tempEdge(x1, y1, x2, y2) {
    const svg = $("#ws-edges");
    const line = document.createElementNS(SVGN, "line");
    line.setAttribute("class", "ws-edge-temp");
    line.setAttribute("x1", x1 + ORIGIN); line.setAttribute("y1", y1 + ORIGIN);
    line.setAttribute("x2", x2 + ORIGIN); line.setAttribute("y2", y2 + ORIGIN);
    svg.appendChild(line);
    return line;
  }
  function onConnectMove(e) {
    if (!drag || drag.type !== "connect") return;
    const node = nodeById(drag.id);
    const p = canvasPos(e);
    drag.temp.setAttribute("x2", p.x + ORIGIN);
    drag.temp.setAttribute("y2", p.y + ORIGIN);
    // highlight the hovered input handle
    $$(".wf-node").forEach((c) => c.classList.remove("connect-hover"));
    const target = e.target.closest(".wf-in");
    if (target) target.closest(".wf-node").classList.add("connect-hover");
  }
  function onConnectUp(e) {
    if (drag && drag.type === "connect") {
      const target = e.target.closest(".wf-in");
      if (target) {
        const from = drag.id;
        const to = target.closest(".wf-node").dataset.id;
        if (from !== to && !S.workflow.edges.some((x) => x.source === from && x.target === to)) {
          S.workflow.edges.push({ source: from, target: to, condition: "" });
          markDirty();
          renderEdges();
        }
      }
      drag.temp.remove();
      drag = null;
      $$(".wf-node").forEach((c) => c.classList.remove("connect-hover"));
    }
    window.removeEventListener("pointermove", onConnectMove);
    window.removeEventListener("pointerup", onConnectUp);
  }

  /* ── canvas pan / zoom ────────────────────────────────────────── */
  function bindCanvasPan() {
    const canvas = $("#ws-canvas");
    let pan = null;
    canvas.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".wf-node") || e.target.closest(".ws-edge")) return;
      if (e.button !== 0 && e.button !== 1) return;
      e.preventDefault();
      pan = { x: e.clientX, y: e.clientY, tx: S.tx, ty: S.ty };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!pan) return;
      S.tx = pan.tx + (e.clientX - pan.x);
      S.ty = pan.ty + (e.clientY - pan.y);
      render();
    });
    canvas.addEventListener("pointerup", () => { pan = null; });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = Math.pow(1.15, -e.deltaY / 100);
      const r = canvas.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      S.zoom = Math.min(2, Math.max(0.4, S.zoom * factor));
      // keep the point under the cursor fixed
      S.tx = px - (px - S.tx) * factor;
      S.ty = py - (py - S.ty) * factor;
      render();
    }, { passive: false });
    canvas.addEventListener("click", (e) => {
      if (e.target === canvas || e.target.closest("#ws-edges")) select("node", null);
    });
  }

  /* ── properties panel ─────────────────────────────────────────── */
  function renderProps() {
    const body = $("#ws-props-body");
    empty(body);
    if (S.selected.type === "node") return renderNodeProps(body);
    if (S.selected.type === "edge") return renderEdgeProps(body);
    body.appendChild(el("div", "placeholder", "select a node or edge to configure it"));
  }

  function setRow(label, input) {
    const wrap = el("div", "set-row");
    wrap.appendChild(el("label", null, label));
    wrap.appendChild(input);
    return wrap;
  }

  function renderNodeProps(body) {
    const n = nodeById(S.selected.id);
    if (!n) return;

    const label = el("input");
    label.value = n.label || "";
    label.addEventListener("input", () => { n.label = label.value; markDirty(); renderNodes(); });
    body.appendChild(setRow("Label", label));

    const kind = el("select");
    ["agent", "end"].forEach((k) => { const o = el("option", null, k); o.value = k; if (n.kind === k) o.selected = true; kind.appendChild(o); });
    kind.addEventListener("change", () => { n.kind = kind.value; markDirty(); renderNodes(); renderProps(); });
    body.appendChild(setRow("Kind", kind));

    if (n.kind === "agent") {
      const agentSel = el("select");
      const none = el("option", null, "(no agent)");
      none.value = "";
      agentSel.appendChild(none);
      S.agents.forEach((a) => {
        const o = el("option", null, `${a.tag.toUpperCase()} · ${a.name}`);
        o.value = a.agent;
        if (n.agent === a.agent) o.selected = true;
        agentSel.appendChild(o);
      });
      agentSel.value = n.agent || "";
      agentSel.addEventListener("change", () => { n.agent = agentSel.value; markDirty(); renderNodes(); });
      body.appendChild(setRow("Agent", agentSel));

      const modelRow = setRow("Model", modelCombo(n));
      body.appendChild(modelRow);
      const agentHint = agentByKey(n.agent);
      if (!n.model && agentHint && agentHint.model) {
        body.appendChild(el("p", "set-note",
          `Auto → resolves to ${agentHint.model} (agent default from opencode.json)`));
      }
    }

    const rolesBox = el("div", "ws-roles-box");
    S.roles.forEach((r) => {
      const lab = el("label", "ws-role-chip");
      const cb = el("input");
      cb.type = "checkbox";
      cb.checked = (n.roles || []).includes(r.id);
      cb.addEventListener("change", () => {
        if (cb.checked) { if (!n.roles.includes(r.id)) n.roles.push(r.id); }
        else n.roles = n.roles.filter((x) => x !== r.id);
        markDirty(); renderNodes();
      });
      lab.appendChild(cb);
      lab.appendChild(el("span", null, r.name || r.id));
      rolesBox.appendChild(lab);
    });
    body.appendChild(setRow("Roles", rolesBox));

    if (n.kind === "agent") {
      // Prompt Profile — the optional *source* of the node's Instruction. The
      // Instruction textarea stays the editable final value (never auto-wiped).
      const promptSel = el("select", "ws-prompt-select");
      const none = el("option", null, "None");
      none.value = "";
      promptSel.appendChild(none);
      const suggested = suggestPromptsForNode(n);
      if (suggested.length) {
        const sg = el("optgroup");
        sg.label = "Suggested";
        suggested.forEach((p) => {
          const o = el("option", null, p.name);
          o.value = p.id;
          sg.appendChild(o);
        });
        promptSel.appendChild(sg);
      }
      const all = el("optgroup");
      all.label = "All Prompts";
      S.prompts.forEach((p) => {
        const o = el("option", null, p.name);
        o.value = p.id;
        all.appendChild(o);
      });
      promptSel.appendChild(all);
      promptSel.value = n.prompt_profile || "";

      const preview = el("div", "ws-prompt-preview hidden");
      const apply = el("button", "btn ws-prompt-apply hidden");
      apply.type = "button";
      apply.textContent = "Apply Prompt";

      function refreshPreview() {
        const p = S.promptById[n.prompt_profile];
        empty(preview);
        if (!p) {
          preview.classList.add("hidden");
          apply.classList.add("hidden");
          return;
        }
        preview.classList.remove("hidden");
        apply.classList.remove("hidden");
        preview.appendChild(el("div", "ws-prompt-preview-name", p.name));
        if (p.description) preview.appendChild(el("div", "ws-prompt-preview-desc", p.description));
        const caps = (p.capabilities || []).join(" · ");
        if (caps) preview.appendChild(el("div", "ws-prompt-preview-caps", "Capabilities: " + caps));
      }

      promptSel.addEventListener("change", async () => {
        await onPromptSelected(n, promptSel.value);
        renderProps();   // refresh the Instruction textarea (and preview)
      });
      apply.addEventListener("click", async () => {
        await applyPromptToNode(n, n.prompt_profile);
        renderProps();
      });

      body.appendChild(setRow("Prompt Profile", promptSel));
      body.appendChild(preview);
      body.appendChild(apply);
      refreshPreview();
    }

    const instructions = el("textarea");
    instructions.placeholder = "per-node instructions (override the agent's default behavior)";
    instructions.value = n.instructions || "";
    instructions.addEventListener("input", () => { n.instructions = instructions.value; markDirty(); });
    body.appendChild(setRow("Instructions", instructions));

    if (n.kind === "agent") {
      // Task / Purpose + deterministic recommendation (Phase 2).
      const taskInput = el("textarea", "ws-task-input");
      taskInput.placeholder = "Optional task description (e.g. \"find authentication vulnerabilities\")";
      taskInput.value = nodeTaskDescription(n);
      taskInput.addEventListener("input", () => {
        n.task = Object.assign({}, n.task || {}, { description: taskInput.value });
        markDirty();
      });
      body.appendChild(setRow("Task / Purpose", taskInput));

      const suggestBtn = el("button", "btn ws-suggest-prompt");
      suggestBtn.type = "button";
      suggestBtn.textContent = "Suggest Prompt";
      suggestBtn.addEventListener("click", () => suggestPrompt(n));
      body.appendChild(suggestBtn);

      renderRecommendationPreview(body, n);
      renderModelCapabilityPreview(body, n);
      renderModelRecommendation(body, n);
      renderModelDetails(body, n);
    }

    const tools = el("input");
    tools.placeholder = "comma-separated tools";
    tools.value = (n.tools || []).join(", ");
    tools.addEventListener("input", () => { n.tools = tools.value.split(",").map((s) => s.trim()).filter(Boolean); markDirty(); });
    body.appendChild(setRow("Tools", tools));

    const enabled = el("input");
    enabled.type = "checkbox";
    enabled.checked = n.enabled;
    enabled.addEventListener("change", () => { n.enabled = enabled.checked; markDirty(); renderNodes(); });
    body.appendChild(setRow("Enabled", enabled));

    const actions = el("div", "wizard-actions");
    const dup = el("button", "btn", "Duplicate");
    dup.addEventListener("click", () => {
      const copy = Object.assign({}, n, { id: nextId(), x: n.x + 60, y: n.y + 60, roles: (n.roles || []).slice() });
      S.workflow.nodes.push(copy);
      markDirty(); render(); select("node", copy.id);
    });
    const del = el("button", "btn danger", "Remove");
    del.addEventListener("click", () => {
      S.workflow.nodes = S.workflow.nodes.filter((x) => x.id !== n.id);
      S.workflow.edges = S.workflow.edges.filter((e) => e.source !== n.id && e.target !== n.id);
      S.selected = { type: null, id: null };
      markDirty(); render(); renderProps();
    });
    actions.appendChild(dup);
    actions.appendChild(del);
    body.appendChild(actions);
  }

  function renderEdgeProps(body) {
    const e = edgeByKey(S.selected.id);
    if (!e) return;
    const from = el("input"); from.value = e.source; from.disabled = true;
    body.appendChild(setRow("From", from));
    const to = el("input"); to.value = e.target; to.disabled = true;
    body.appendChild(setRow("To", to));

    const cond = el("select");
    [["", "unconditional"], ["success", "success"], ["failure", "failure"]].forEach(([v, l]) => {
      const o = el("option", null, l); o.value = v; if (e.condition === v) o.selected = true; cond.appendChild(o);
    });
    cond.addEventListener("change", () => { e.condition = cond.value; markDirty(); renderEdges(); });
    body.appendChild(setRow("Condition", cond));

    const note = el("p", "set-note",
      "success → flows when the source completes · failure → flows when the source fails (used for retry loops) · unconditional → always flows");
    body.appendChild(note);

    const del = el("button", "btn danger", "Remove edge");
    del.addEventListener("click", () => {
      const key = edgeKey(e);
      S.workflow.edges = S.workflow.edges.filter((x) => edgeKey(x) !== key);
      S.selected = { type: null, id: null };
      markDirty(); renderEdges(); renderProps();
    });
    body.appendChild(del);
  }

  /* ── workflow CRUD ────────────────────────────────────────────── */
  const LAST_WF_KEY = "zova-last-workflow";
  function rememberWorkflow(id) {
    try { window.localStorage.setItem(LAST_WF_KEY, id); } catch (_) { /* private mode */ }
  }
  function forgetWorkflow() {
    try { window.localStorage.removeItem(LAST_WF_KEY); } catch (_) { /* ignore */ }
  }
  function lastWorkflow() {
    try { return window.localStorage.getItem(LAST_WF_KEY) || ""; } catch (_) { return ""; }
  }

  async function loadWorkflowList() {
    let list = [];
    try { list = (await api("/api/workflows")).workflows || []; } catch (_) { /* empty */ }
    const sel = $("#ws-workflow-select");
    empty(sel);
    const none = el("option", null, "(no workflow loaded)");
    none.value = "";
    sel.appendChild(none);
    list.forEach((w) => {
      const o = el("option", null, `${w.name || w.id} (${w.nodes} nodes)`);
      o.value = w.id;
      sel.appendChild(o);
    });
  }

  async function loadWorkflow(id) {
    if (!id) { newWorkflow(); return; }
    try {
      const data = await api(`/api/workflows/${encodeURIComponent(id)}`);
      S.workflow = data.workflow;
      S.nid = Math.max(S.nid, S.workflow.nodes.length);
      S.runStatuses = {}; S.waves = {}; S.taskRecs = {};
      rememberWorkflow(id);
      markClean();
      render();
      renderProps();
    } catch (err) {
      setError(err.message);
    }
  }

  function newWorkflow() {
    const name = window.prompt("Workflow id (e.g. my-pipeline):", "my-pipeline");
    if (!name) return;
    S.workflow = { id: name.trim().toLowerCase().replace(/\s+/g, "-"), name: "", project: "",
                   nodes: [], edges: [], entry: [], state: {}, settings: { max_iterations: 3 } };
    S.runStatuses = {}; S.waves = {}; S.taskRecs = {};
    markClean(); render(); renderProps(); loadWorkflowList();
  }

  async function saveWorkflow() {
    setError("");
    const wf = S.workflow;
    // "untitled" is a placeholder, never a persistent workflow id. Require a
    // real id before saving — but never call newWorkflow() here, because that
    // resets the graph and would discard the nodes the user just built.
    if (!wf.id || wf.id === "untitled") {
      const name = window.prompt("Workflow id (e.g. my-pipeline):", "my-pipeline");
      if (!name || !name.trim()) {
        setError("save cancelled — a workflow id is required");
        return null;
      }
      wf.id = name.trim().toLowerCase().replace(/\s+/g, "-");
    }
    try {
      const r = await put(`/api/workflows/${encodeURIComponent(wf.id)}`, wf);
      // Adopt the server-returned workflow so S.workflow.id is the real,
      // normalized persisted id (never the "untitled" placeholder).
      S.workflow = r.workflow;
      rememberWorkflow(S.workflow.id);
      markClean();
      setOk("saved ✓");
      loadWorkflowList();
      return S.workflow;
    } catch (err) { setError(err.message); return null; }
  }

  /* ── activate: connect the loaded workflow to Home + Runtime ──────
     The single source of truth stays ``active_workflow_id`` (backend prefs).
     Activate saves the workflow first when dirty (never activates an outdated
     version), PUTs the existing /api/active-workflow contract, then verifies
     via GET that the backend reports this exact id as active. */
  async function activateWorkflow() {
    setError("");
    // Resolve an untitled/id-less or dirty workflow into a persisted one first.
    // saveWorkflow() requires a real id for untitled workflows (never invents
    // one), adopts the server-returned workflow, and returns it — or null when
    // the save is cancelled/failed (the error is already surfaced).
    if (!S.workflow.id || S.workflow.id === "untitled" || S.dirty) {
      const saved = await saveWorkflow();
      if (!saved) return;
    }
    const id = S.workflow.id;
    try {
      // Existing API contract: PUT /api/active-workflow { workflow_id }.
      await put("/api/active-workflow", { workflow_id: id });
      // Verify the result (requirement: active_workflow_id === current id).
      const active = await api("/api/active-workflow");
      S.activeWorkflowId = active.active_workflow_id || null;
      updateActivateButton();
      if (S.activeWorkflowId === id) {
        setOk("✓ Active — Home projects this workflow");
      } else {
        setError(`activation failed: active_workflow_id is ${JSON.stringify(S.activeWorkflowId)}`);
      }
    } catch (err) {
      // Surface the actual API error; the workflow graph is untouched.
      setError(err.message);
    }
  }

  async function refreshActiveIndicator() {
    let activeId = null;
    try {
      const active = await api("/api/active-workflow");
      activeId = active.active_workflow_id || null;
    } catch (_) { /* keep null — indicator shows "not active" */ }
    S.activeWorkflowId = activeId;
    updateActivateButton();
  }

  function updateActivateButton() {
    const btn = $("#ws-activate");
    if (!btn) return;
    const isActive = !!S.activeWorkflowId && S.activeWorkflowId === S.workflow.id;
    btn.textContent = isActive ? "✓ Active" : "Activate Workflow";
    btn.classList.toggle("active", isActive);
    btn.title = isActive
      ? "This workflow is active on Home (click to re-activate)"
      : "Make this workflow the active one for Home";
  }

  function formatErrors(errors) {
    return (errors || []).map((e) => `• ${e.node ? e.node + ": " : ""}${e.message}`).join("\n");
  }

  function clearValidation() {
    const box = $("#ws-validation");
    if (box) { box.classList.add("hidden"); box.innerHTML = ""; }
  }

  function showValidation(text, kind) {
    const box = $("#ws-validation");
    if (!box) return;
    box.classList.remove("hidden");
    box.className = "ws-validation" + (kind ? " " + kind : "");
    box.textContent = text || "";
  }

  async function validateWorkflow() {
    if (S.dirty) await saveWorkflow();
    if (!S.workflow.id) { setError("save the workflow first"); return; }
    try {
      const r = await api(`/api/workflows/${encodeURIComponent(S.workflow.id)}/validate`);
      if (r.valid) {
        setOk("valid ✓");
        showValidation("✓ Workflow is valid and ready to run.", "ok");
      } else {
        setError("Workflow cannot run.");
        showValidation("Workflow cannot run.\n\n" + formatErrors(r.errors), "err");
      }
    } catch (err) {
      setError(err.message);
      showValidation(err.message, "err");
    }
  }

  async function dryRunWorkflow() {
    setError("");
    const wf = S.workflow;
    if (!wf.id) { setError("save the workflow first"); return; }
    try {
      const r = await post(`/api/workflows/${encodeURIComponent(wf.id)}/dry-run`, wf);
      S.waves = {};
      (r.waves || []).forEach((wave, i) => wave.forEach((id) => { S.waves[id] = i + 1; }));
      renderNodes();
      const order = (r.waves || []).map((wave, i) => `${i + 1}. ${wave.join(" + ")}`).join("\n");
      const conds = (r.conditional_edges || [])
        .map((e) => `${e.source} —${e.condition}→ ${e.target}`).join(", ");
      showValidation(
        "Dry run (no agents dispatched)\n\nExecution order:\n" + (order || "(no nodes)") +
        (conds ? "\n\nConditional edges: " + conds : "") +
        `\n\nLoop bound: max_iterations = ${r.max_iterations ?? 3}`, "plan");
      setOk("dry run ✓");
    } catch (err) {
      showValidation(err.message, "err");
      setError(err.message);
    }
  }

  async function runWorkflow() {
    if (S.dirty) await saveWorkflow();
    if (!S.workflow.id) { setError("save the workflow first"); return; }
    setError("");
    try {
      const r = await post(`/api/workflows/${encodeURIComponent(S.workflow.id)}/run`, { initial_state: {} });
      S.runId = r.run_id;
      $("#ws-run").classList.add("hidden");
      $("#ws-run-cancel").classList.remove("hidden");
      pollRun();
    } catch (err) {
      setError(typeof err.message === "string" && err.message.indexOf("{") === 0
        ? "Workflow cannot run.\n" + JSON.parse(err.message).errors.map((x) => `• ${x.node ? x.node + ": " : ""}${x.message}`).join("\n")
        : err.message);
    }
  }

  async function pollRun() {
    if (!S.runId) return;
    try {
      const snap = await api(`/api/workflows/runs/${encodeURIComponent(S.runId)}`);
      applyRunStatuses(snap);
      if (snap.finished) {
        $("#ws-run").classList.remove("hidden");
        $("#ws-run-cancel").classList.add("hidden");
        const failed = Object.values(snap.statuses).filter((s) => s === "failed").length;
        setError(failed ? `finished — ${failed} node(s) failed` : "finished ✓");
        S.runId = null;
        return;
      }
    } catch (_) { /* run may have been cleaned up */ }
    setTimeout(pollRun, 500);
  }

  async function cancelRun() {
    if (!S.runId) return;
    try { await post(`/api/workflows/runs/${encodeURIComponent(S.runId)}/cancel`); } catch (_) { /* ignore */ }
    $("#ws-run").classList.remove("hidden");
    $("#ws-run-cancel").classList.add("hidden");
    S.runId = null;
  }

  /* ── run status overlay ───────────────────────────────────────── */
  function applyRunStatuses(snap) {
    S.runStatuses = (snap && snap.statuses) || {};
    $$(".wf-node").forEach((c) => {
      const id = c.dataset.id;
      const n = nodeById(id);
      const st = n ? nodeState(n) : null;
      c.classList.remove("st-completed", "st-failed", "st-running", "st-skipped", "st-disabled");
      if (st) c.classList.add("st-" + st);
      const dot = c.querySelector(".wf-node-dot");
      if (dot) {
        dot.classList.remove("st-ready", "st-waiting", "st-running", "st-completed",
                              "st-failed", "st-skipped", "st-disabled", "st-terminal");
        if (st) dot.classList.add("st-" + st);
      }
      const stateEl = c.querySelector(".wf-node-state");
      if (stateEl && st) stateEl.textContent = STATE_LABEL[st] || "Ready";
    });
  }

  /* ── templates + recommend ────────────────────────────────────── */
  async function loadTemplates() {
    let names = [];
    try { names = (await api("/api/workflows/templates")).templates || []; } catch (_) { /* empty */ }
    const sel = $("#ws-template-select");
    empty(sel);
    const none = el("option", null, "— preset —");
    none.value = "";
    sel.appendChild(none);
    names.forEach((n) => {
      const o = el("option", null, TEMPLATE_LABELS[n] || n);
      o.value = n;
      sel.appendChild(o);
    });
  }

  async function loadTemplate() {
    const name = $("#ws-template-select").value;
    if (!name) return;
    setError("");
    try {
      // The backend contract is POST /api/workflows/from-template/{name}.
      const r = await post(`/api/workflows/from-template/${encodeURIComponent(name)}`);
      // Fully replace the graph — never merge with the previous workflow and
      // never auto-persist (the template keeps its own id until the user saves,
      // so a previous workflow on disk can't be overwritten by accident).
      S.workflow = r.workflow;
      recalcNid();
      S.runStatuses = {}; S.waves = {}; S.taskRecs = {};
      S.selected = { type: null, id: null };   // clear the previous selection
      markDirty();
      render();
      renderProps();
      // Fit the camera (zoom/tx/ty) to the loaded graph on the next frame —
      // never touching the template's node coordinates.
      requestAnimationFrame(() => fitToScreen());
      setOk(`Template "${TEMPLATE_LABELS[name] || name}" loaded — ${S.workflow.nodes.length} nodes · ${S.workflow.edges.length} edges`);
    } catch (err) { setError(err.message); }
  }

  async function recommend() {
    const n = window.prompt("Number of agents:", "4");
    if (!n) return;
    try {
      const r = await api(`/api/workflows/recommend?agents=${encodeURIComponent(n)}`);
      S.workflow = r.workflow;
      S.nid = Math.max(S.nid, S.workflow.nodes.length);
      S.runStatuses = {}; S.waves = {}; S.taskRecs = {};
      markDirty(); render(); renderProps();
      const reasons = Object.entries(r.reasons || {}).map(([id, why]) => `${id} → ${why}`).join("\n");
      setOk("Suggested workflow loaded.\n" + (reasons || ""));
    } catch (err) { setError(err.message); }
  }

  /* ── misc ─────────────────────────────────────────────────────── */
  function setOk(msg) { const s = $("#ws-status"); s.textContent = msg; s.className = "ws-status ok"; }
  function setError(msg) { const s = $("#ws-status"); s.textContent = msg; s.className = "ws-status err"; }

  function bind() {
    $("#ws-new").addEventListener("click", newWorkflow);
    $("#ws-save").addEventListener("click", saveWorkflow);
    $("#ws-activate").addEventListener("click", activateWorkflow);
    $("#ws-load").addEventListener("click", () => loadWorkflow($("#ws-workflow-select").value));
    $("#ws-workflow-select").addEventListener("change", () => loadWorkflow($("#ws-workflow-select").value));
    $("#ws-validate").addEventListener("click", validateWorkflow);
    $("#ws-run").addEventListener("click", runWorkflow);
    $("#ws-dry-run").addEventListener("click", dryRunWorkflow);
    $("#ws-run-cancel").addEventListener("click", cancelRun);
    $("#ws-add-agent").addEventListener("click", () => {
      // secondary entry point: focus + reset the library search (the library
      // itself is the primary visible interaction — click or drag an agent).
      const search = $("#ws-agent-search");
      if (search) { search.value = ""; S.agentFilter = ""; renderLibrary(); search.focus(); }
    });
    const agentSearch = $("#ws-agent-search");
    if (agentSearch) {
      agentSearch.addEventListener("input", () => {
        S.agentFilter = agentSearch.value;
        renderLibrary();
      });
      agentSearch.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const agents = matchingAgents();
          if (agents.length) addNode(agents[0]);
        }
      });
    }
    $("#ws-template-load").addEventListener("click", loadTemplate);
    $("#ws-recommend").addEventListener("click", recommend);
    $("#ws-duplicate").addEventListener("click", async () => {
      if (!S.workflow.id) { setError("save the workflow first"); return; }
      try {
        const r = await post(`/api/workflows/${encodeURIComponent(S.workflow.id)}/duplicate`);
        setOk(`duplicated → ${r.workflow.id}`); loadWorkflowList();
      } catch (err) { setError(err.message); }
    });
    $("#ws-delete").addEventListener("click", async () => {
      if (!S.workflow.id) return;
      if (!window.confirm(`Delete workflow "${S.workflow.id}"?`)) return;
      try {
        await del(`/api/workflows/${encodeURIComponent(S.workflow.id)}`);
        forgetWorkflow();
        setOk("deleted"); newWorkflow();
      } catch (err) { setError(err.message); }
    });
    $("#ws-zoom-in").addEventListener("click", () => { S.zoom = Math.min(2, S.zoom * 1.25); render(); });
    $("#ws-zoom-out").addEventListener("click", () => { S.zoom = Math.max(0.4, S.zoom / 1.25); render(); });
    $("#ws-zoom-reset").addEventListener("click", fitToScreen);
    window.addEventListener("beforeunload", (e) => {
      if (S.dirty) { e.preventDefault(); e.returnValue = ""; }
    });
    // Close an open model combobox when clicking anywhere outside it.
    document.addEventListener("click", (e) => {
      $$(".ws-model-combo").forEach((box) => {
        if (!box.contains(e.target)) {
          box.querySelector(".combo-list").classList.add("hidden");
        }
      });
    });
    bindDragDrop();
    bindCanvasPan();
  }

  function init() {
    bind();
    loadMeta().then(() => {});
    loadWorkflowList().then(() => {
      // restore the most recently edited workflow so a browser refresh never
      // silently drops nodes that were already saved.
      const last = lastWorkflow();
      if (last) loadWorkflow(last);
    });
    loadTemplates();
    refreshActiveIndicator();
    render();
  }

  window.MACWorkspace = { S, select, render, addNode, saveWorkflow, loadWorkflow,
                          validateWorkflow, runWorkflow, dryRunWorkflow, fitToScreen,
                          loadMeta, matchingAgents, bindDragDrop, ORIGIN,
                          activateWorkflow, refreshActiveIndicator, updateActivateButton,
                          loadTemplate, recalcNid,
                          promptRoleKey, suggestPromptRole, nodePromptRoleKeys,
                          suggestPromptsForNode, fetchPromptText,
                          applyPromptToNode, onPromptSelected,
                          nodeTaskDescription, nodePromptRole, suggestPrompt,
                          renderRecommendationPreview, renderModelCapabilityPreview,
                          loadModelCatalog, modelProviderOptions, modelDisplayName,
                          renderModelRecommendation, renderModelDetails };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

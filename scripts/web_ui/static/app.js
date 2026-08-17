/* ─────────────────────────────────────────────────────────────────────
   app.js — MultiAgentCoding dashboard frontend
   Vanilla JS, no build step, no CDN. Layout + interactions only; every
   mutation flows through the REST/SSE API backed by the existing core.
   ───────────────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  const STATUS_LABEL = { idle: "idle", thinking: "thinking", active: "active", error: "error" };
  const TASK_STATUSES = ["planned", "ready", "in_progress", "blocked", "completed", "failed"];
  const FOLDER_ORDER = ["root", "00-System", "01-Architecture", "02-Agents", "03-Tasks",
                        "04-Decisions", "05-Documentation", "06-Testing"];
  const FOLDER_COLOR = {
    "root": "var(--folder-root)", "00-System": "var(--folder-00)",
    "01-Architecture": "var(--folder-01)", "02-Agents": "var(--folder-02)",
    "03-Tasks": "var(--folder-03)", "04-Decisions": "var(--folder-04)",
    "05-Documentation": "var(--folder-05)", "06-Testing": "var(--folder-06)",
  };

  // `cx` color resolved at run-time (cf. AGENTS.vacancy)
  function cssVar(name) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || "#888";
  }

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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
    if (!res.ok) throw Object.assign(new Error((data && data.detail) || res.statusText), { status: res.status, data });
    return data;
  }

  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  // Per-agent session tail for the frontend in-memory mirror — matches the
  // backend WebState.SESSION_TAIL so rebuilds never balloon memory.
  const SESSION_TAIL = 800;
  // Event kinds rendered as rows in an agent panel console. status events are
  // persisted (so rebuilds never lose them) but only ever update the dot, so
  // they are never appended as console rows — live and replay stay identical.
  const PANEL_KINDS = ["run", "line", "error", "usermsg", "taskline"];

  // Resize handles: every edge + corner of an agent window. Each direction
  // names which edges move (e.g. "nw" moves the top + left edges). The handle
  // DOM carries data-dir; bindPanelInteractions maps pointer deltas through
  // resizeNodeDelta using these edge flags.
  const RESIZE_DIRS = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
  const RESIZE_EDGES = {
    n: { h: null, v: "n" }, s: { h: null, v: "s" },
    e: { h: "e", v: null }, w: { h: "w", v: null },
    ne: { h: "e", v: "n" }, nw: { h: "w", v: "n" },
    se: { h: "e", v: "s" }, sw: { h: "w", v: "s" },
  };

  // Professional agent-window avatar palette (indexed by agent tag m1…m7).
  const AVATAR_COLORS = [
    "#7c6cd9", "#58a6ff", "#3fb950", "#f0883e", "#d2a8ff", "#79c0ff", "#ffa657",
  ];
  function avatarColor(tag) {
    const n = parseInt(String(tag || "").replace(/\D/g, ""), 10);
    return AVATAR_COLORS[(Number.isFinite(n) ? n : 1) - 1] || AVATAR_COLORS[0];
  }

  // Bottom dock: minimized height (just the tab bar) + storage key.
  const BOTTOM_MIN_H = 34;
  const BOTTOM_MIN_KEY = "zova-bottom-minimized";
  const BOTTOM_H_KEY = "zova-bottom-h";

  /* ── Home layout system ──────────────────────────────────────────
     The workflow graph (nodes/edges/x/y) is the single source of truth; the
     Home layout layer is independent and only controls how that graph is shown.
     Layout state is persisted separately (localStorage, keyed by workflow id)
     and never mutates WorkflowNode.x/y or WorkflowEdge values. */
  const HOME_LAYOUTS = ["workflow", "grid", "horizontal", "vertical", "compact", "custom"];
  const HOME_GAP = 12;                     // grid/flow spacing
  const HOME_PAD = 24;                     // viewport padding
  const HOME_ZOOM_MIN = 0.5, HOME_ZOOM_MAX = 1.5;
  const HOME_LAYOUT_KEY = "zova-home-layouts";
  const HOME_MODE_KEY = "zova-home-mode";

  // Panel-sizing policy, centralized in CSS variables (--home-panel-*) so the
  // whole dashboard shares one readable size spec. cssSize reads them at render
  // time with fallbacks for headless/older environments.
  function cssSize(varName, fallback) {
    try {
      const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
      const v = parseFloat(raw);
      if (Number.isFinite(v) && v > 0) return v;
    } catch (_) { /* no CSSOM */ }
    return fallback;
  }
  function panelSizes() {
    return {
      minW: cssSize("--home-panel-min-w", 280),
      minH: cssSize("--home-panel-min-h", 200),
      prefW: cssSize("--home-panel-pref-w", 360),
      prefH: cssSize("--home-panel-pref-h", 260),
      compactW: cssSize("--home-panel-compact-w", 160),
      compactH: cssSize("--home-panel-compact-h", 96),
      resizeMinW: cssSize("--home-panel-resize-min-w", 280),
      resizeMinH: cssSize("--home-panel-resize-min-h", 180),
    };
  }

  /* ─────────────────────────── state ─────────────────────────── */
  const Ag = {
    agents: [],                 // roster from /api/agents
    sessions: {},               // tag -> [{kind,text,n}]
    prefs: { layout: "4", agents_visible: [], active_tag: null, selected_node: null },
    graph: { nodes: [], edges: [] },
    view: { nodes: [], edges: [] },   // current filtered/laid-out graph
    sectionFilter: [],                // empty = All sections
    coreView: false,                  // Core/Important architecture map
    tasks: [],
    selectedNode: null,
    activeTag: null,
    taskDetail: null,
    logKey: "orchestrator",
    // Active-workflow projection: when set, the Workflow Designer graph is the
    // single source of truth for the Home agent windows (panels, positions,
    // edges) instead of the registry/prefs panel set.
    homeWorkflow: null,        // {id,name,nodes,edges} | null
    homeNodes: [],             // workflow agent nodes in canonical layout order
    homeEdges: [],             // [{source,target,condition}]
    homeSignature: "",         // signature of the projected graph (reconcile on change)
    nodeSessions: {},          // workflowNodeId -> [{kind,text,n}] (per-node, independent)
    runStatuses: {},           // workflowNodeId -> run status (empty when idle)
    runEmitted: {},            // runId -> {nodeId: true} (already-replayed outputs)
    activeRunId: null,         // workflow run currently streaming into Home
    activeNodeId: null,        // selected workflow node id (Home)
    // Home visual layout layer (independent of the workflow graph).
    homeMode: "workflow",      // selected Home layout mode
    homeZoom: 1,               // Home panel/graph zoom (0.5–1.5)
    homeLayouts: {},           // wfId -> {mode, zoom, nodes: {nodeId: {x,y,width,height}}}
    homePositions: new Map(),  // last-rendered nodeId -> {x,y} (center)
    homeSizes: new Map(),      // last-rendered nodeId -> {w,h}
    homeZTop: 0,               // z-index counter for bring-to-front
    // Bottom Status/Tasks/Execution/Logs dock (minimizable, reflows panels).
    bottomMinimized: false,
    bottomExpandedH: null,     // last expanded --bottom-h before minimize
  };

  /* ─────────────────────── toolbar wiring ────────────────────── */
  function bindLayout() {
    $$(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        Ag.prefs.layout = btn.dataset.layout;
        $$(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
        savePrefs(); buildWorkspace();
      });
    });
  }

  // Home layout toolbar: mode selector + zoom + reset (visual layer only).
  function bindHomeLayout() {
    const sel = $("#home-layout-select");
    if (sel) sel.addEventListener("change", () => setHomeLayout(sel.value));
    const zin = $("#home-zoom-in"), zout = $("#home-zoom-out");
    if (zin) zin.addEventListener("click", () => setHomeZoom(currentHomeLayout().zoom + 0.1));
    if (zout) zout.addEventListener("click", () => setHomeZoom(currentHomeLayout().zoom - 0.1));
    const reset = $("#home-layout-reset");
    if (reset) reset.addEventListener("click", resetHomeLayout);
  }

  function togglePop(show) { $("#agents-pop").classList.toggle("hidden", !show); }
  function bindAgentsPop() {
    $("#agents-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      togglePop($("#agents-pop").classList.contains("hidden"));
    });
    document.addEventListener("click", () => togglePop(false));
  }

  function buildPop() {
    const pop = $("#agents-pop");
    empty(pop);
    const hint = el("div", "pop-hint", "max 6 panels visible");
    pop.appendChild(hint);
    const visible = Ag.prefs.agents_visible || [];
    Ag.agents.forEach((a) => {
      const isVisible = visible.includes(a.tag);
      const atCap = visible.length >= 6 && !isVisible;
      const item = el("label", "pop-item" + (atCap ? " disabled" : ""));
      const cb = el("input");
      cb.type = "checkbox";
      cb.checked = isVisible;
      cb.disabled = atCap;
      item.appendChild(cb);
      item.appendChild(el("span", "pop-name", `${a.tag.toUpperCase()} · ${a.name}`));
      item.appendChild(el("span", "pop-model", a.model || ""));
      item.addEventListener("click", (e) => { if (atCap) e.preventDefault(); });
      cb.addEventListener("change", () => {
        let next = visible.filter((t) => t !== a.tag);
        if (cb.checked) next.push(a.tag); // keeps roster order stable, append at end
        Ag.prefs.agents_visible = next;
        if (!cb.checked && Ag.activeTag === a.tag) {
          Ag.prefs.active_tag = next[0] || null;
          Ag.activeTag = Ag.prefs.active_tag;
        }
        savePrefs(); buildPop(); buildWorkspace();
      });
      pop.appendChild(item);
    });
  }

  function buildDispatchTarget() {
    const sel = $("#prompt-target");
    empty(sel);
    const active = el("option", null, "Active panel");
    active.value = "active";
    const all = el("option", null, "All agents (M1–M7)");
    all.value = "all";
    sel.appendChild(active);
    sel.appendChild(all);
    if (Ag.homeNodes.length) {
      // A Home command with an active workflow runs the whole graph — the
      // backend ignores the per-agent target in that mode.
      const wfOpt = el("option", null,
        "Active workflow · " + (Ag.homeWorkflow ? (Ag.homeWorkflow.name || Ag.homeWorkflow.id) : "graph"));
      wfOpt.value = "workflow";
      sel.insertBefore(wfOpt, all);
      Ag.homeNodes.forEach((n) => {
        const opt = el("option", null, n.label + (n.model ? " · " + n.model : " · Auto"));
        opt.value = "node:" + n.id;
        sel.appendChild(opt);
      });
    }
    Ag.agents.forEach((a) => {
      const opt = el("option", null, `${a.tag.toUpperCase()} · ${a.name}`);
      opt.value = a.tag;
      sel.appendChild(opt);
    });
  }

  // Which node panels receive a Home command's user message. A ``node:X``
  // target names one node; otherwise the workflow's entry nodes (zero
  // in-degree) receive it first — matching the workflow execution semantics
  // where ``user_prompt`` seeds the entry nodes.
  function dispatchTargetNodes(rawTarget) {
    const nodes = enabledNodes();
    if (!nodes.length) return [];
    if (rawTarget && rawTarget.startsWith("node:")) {
      const id = rawTarget.slice(5);
      return nodes.filter((n) => n.id === id);
    }
    const indeg = new Map(nodes.map((n) => [n.id, 0]));
    (Ag.homeEdges || []).forEach((ed) => {
      if (indeg.has(ed.target)) indeg.set(ed.target, (indeg.get(ed.target) || 0) + 1);
    });
    const entries = nodes.filter((n) => (indeg.get(n.id) || 0) === 0);
    return entries.length ? entries : nodes;
  }

  // Render the user's own message immediately (frontend state → session + DOM).
  // Never sourced from the backend — the backend only emits a "dispatched"
  // summary, not the message text.
  function renderUserMessage(rawTarget, prompt) {
    const text = "You: " + prompt;
    const nodes = dispatchTargetNodes(rawTarget);
    if (nodes.length) {
      nodes.forEach((n) => nodeEvent(n.id, { kind: "usermsg", text: text }));
      return;
    }
    let tag = rawTarget;
    if (tag === "active") tag = Ag.activeTag;
    if (tag === "all" || tag === "workflow") tag = null;
    if (tag && !Ag.agents.some((a) => a.tag === tag)) tag = null;
    if (tag) {
      const ev = { kind: "usermsg", text: text, tag: tag };
      const sess = (Ag.sessions[tag] = Ag.sessions[tag] || []);
      sess.push(ev);
      const card = panelEl(tag);
      if (card) appendEv(card.querySelector(".p-console"), ev);
    }
  }

  // Flip the target panels to "working" the instant a run is accepted (the
  // real per-node status follows on the next poll — no invented content).
  function markNodesWorking(nodeIds) {
    (nodeIds || []).forEach((id) => {
      Ag.runStatuses[id] = "running";
      const card = $(`.panel[data-workflow-node-id="${id}"]`);
      if (card) {
        setPanelRunStatus(card, "running");
        card.classList.add("running");
      }
    });
  }

  function bindDispatch() {
    const form = $("#prompt-box");
    const input = $("#prompt-input");
    function autosize() {
      input.style.height = "auto";
      const h = Math.min(240, Math.max(56, input.scrollHeight));
      input.style.height = h + "px";
      input.style.overflowY = h >= 240 ? "auto" : "hidden";
    }
    input.addEventListener("input", autosize);
    autosize();
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const prompt = input.value.trim();
      if (!prompt) return;
      const rawTarget = $("#prompt-target").value;
      let tag = rawTarget;
      if (tag === "active") tag = Ag.activeTag;
      if (tag === "all" || tag === "workflow") tag = null;
      if (tag && tag.startsWith("node:")) tag = null;   // graph runs as a whole
      if (tag && !Ag.agents.some((a) => a.tag === tag)) tag = null;

      // 1) The user's own message appears immediately in the target window(s).
      const targetNodes = dispatchTargetNodes(rawTarget);
      renderUserMessage(rawTarget, prompt);

      try {
        const resp = await post("/api/dispatch", { prompt, agent: tag });
        // 2) A Home command with an active workflow executes the workflow
        //    graph; track its run and show node-aware working status.
        if (resp && resp.mode === "workflow" && resp.run_id) {
          Ag.activeRunId = resp.run_id;
          Ag.runStatuses = {};
          markNodesWorking(targetNodes.map((n) => n.id));
          pollActiveRun();
        }
        input.value = "";
        autosize();
      } catch (err) {
        console.error("dispatch failed", err);
      }
    });
    $("#stop-all").addEventListener("click", async () => {
      try { await post("/api/stop"); } catch (err) { console.error(err); }
    });
    $("#graph-refresh").addEventListener("click", () => loadGraph(true));
    $("#node-open").addEventListener("click", () => {
      if (Ag.selectedNode) openNodeModal(Ag.selectedNode);
    });
  }

  /* ─────────────────────── agent workspace ───────────────────── */
  function statusCls(status) {
    if (status === "active") return "st-ok";
    if (status === "error") return "st-err";
    if (status === "thinking") return "st-busy";
    return "st-idle";
  }

  function panelFor(a, opts) {
    opts = opts || {};
    const card = el("section", "panel");
    card.dataset.tag = a.tag;
    if (opts.nodeId) card.dataset.workflowNodeId = opts.nodeId;
    const head = el("header", "p-head");
    // Agent avatar: a colored monogram (identity only — never invented content).
    const avatar = el("span", "p-avatar", avatarLabel(a));
    avatar.style.background = avatarColor(a.tag);
    avatar.title = a.name || a.tag || "";
    head.appendChild(avatar);
    const nameWrap = el("span", "p-name-wrap");
    nameWrap.appendChild(el("span", "p-name", `${a.tag.toUpperCase()} · ${a.name}`));
    nameWrap.appendChild(el("span", "p-model", a.model || ""));
    head.appendChild(nameWrap);
    const status = el("span", "p-status st-idle");
    status.appendChild(el("span", "dot"));
    status.appendChild(el("span", "p-status-label", "idle"));
    head.appendChild(status);
    if (!opts.noStop) {
      const stop = el("button", "p-stop", "Stop");
      stop.disabled = !a.running;
      stop.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        try { await post(`/api/stop/${a.tag}`); } catch (err) { console.error(err); }
      });
      head.appendChild(stop);
    }
    card.appendChild(head);

    // Current action / state line — reflects the REAL run status only, never
    // fabricated reasoning or hidden chain-of-thought.
    card.appendChild(el("div", "p-action", "idle"));

    const task = el("div", "p-task", a.prompt || "…");
    task.title = a.prompt || "";
    card.appendChild(task);
    const bar = el("div", "p-progress");
    const fill = el("div", "fill");
    fill.style.width = (a.progress || 0) + "%";
    bar.appendChild(fill);
    card.appendChild(bar);

    const consoleEl = el("div", "p-console");
    card.appendChild(consoleEl);
    card.addEventListener("click", () => {
      if (opts.nodeId) setActiveNode(opts.nodeId);
      else setActive(a.tag);
    });

    updatePanelUi(card, a);
    return card;
  }

  // Agent monogram for the avatar (first initial, else the tag).
  function avatarLabel(a) {
    const name = String(a.name || "").trim();
    if (name) return name[0].toUpperCase();
    return String(a.tag || "?").toUpperCase();
  }

  // Map a real run status to the human-readable current-action line.
  function actionLabelFor(status) {
    if (status === "running" || status === "thinking") return "working…";
    if (status === "completed" || status === "active") return "completed";
    if (status === "failed" || status === "error") return "failed";
    if (status === "waiting" || status === "pending") return "waiting";
    return "idle";
  }

  // Update one panel's status dot + label + current-action line from a REAL
  // run status (no invented thinking text).
  function setPanelRunStatus(card, runStatus) {
    const ui = runStatusToUi(runStatus);
    const st = card.querySelector(".p-status");
    if (st) st.className = "p-status " + statusCls(ui);
    const lbl = card.querySelector(".p-status-label");
    if (lbl) lbl.textContent = runStatus || "idle";
    const action = card.querySelector(".p-action");
    if (action) action.textContent = actionLabelFor(runStatus);
  }

  function updatePanelUi(card, a) {
    // Workflow panels (data-workflow-node-id) are driven by the workflow run
    // (node-aware status/session), never by the registry agent row.
    if (card.dataset.workflowNodeId) return;
    const label = card.querySelector(".p-status-label");
    label.textContent = STATUS_LABEL[a.status] || a.status;
    card.querySelector(".p-status").className = "p-status " + statusCls(a.status);
    const action = card.querySelector(".p-action");
    if (action) action.textContent = actionLabelFor(a.status);
    const stop = card.querySelector(".p-stop");
    if (stop) stop.disabled = !a.running;
    card.querySelector(".p-task").textContent = a.prompt || "…";
    card.querySelector(".p-task").title = a.prompt || "";
    card.querySelector(".fill").style.width = (a.progress || 0) + "%";
    const modelEl = card.querySelector(".p-model");
    // Workflow panels (data-node) carry their node's per-instance model — the
    // registry agent's default must not clobber that display.
    if (modelEl && !card.dataset.node) modelEl.textContent = a.model || "";
    card.classList.toggle("active", a.tag === Ag.activeTag);
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function enabledNodes() {
    return (Ag.homeNodes || []).filter((n) => n.enabled !== false);
  }

  // Topological order of nodes (workflow direction: entry nodes first). Cycles
  // and disconnected nodes fall back to their original order.
  function workflowOrder(nodes, edges) {
    const ids = nodes.map((n) => n.id);
    const indeg = new Map(ids.map((id) => [id, 0]));
    const adj = new Map(ids.map((id) => [id, []]));
    (edges || []).forEach((e) => {
      if (indeg.has(e.source) && indeg.has(e.target) && e.source !== e.target) {
        indeg.set(e.target, indeg.get(e.target) + 1);
        adj.get(e.source).push(e.target);
      }
    });
    const queue = ids.filter((id) => indeg.get(id) === 0);
    const order = [];
    const seen = new Set();
    while (queue.length) {
      const id = queue.shift();
      if (seen.has(id)) continue;
      seen.add(id);
      order.push(id);
      (adj.get(id) || []).forEach((t) => {
        indeg.set(t, indeg.get(t) - 1);
        if (indeg.get(t) === 0) queue.push(t);
      });
    }
    ids.forEach((id) => { if (!seen.has(id)) order.push(id); });
    return order;
  }

  function homeAvail() {
    const wg = $("#workspace-grid");
    const w = (wg && wg.clientWidth) || window.innerWidth || 800;
    const h = (wg && wg.clientHeight) || window.innerHeight || 600;
    // floor at the readable minimum so a tiny viewport never collapses to zero
    return { w: Math.max(280, w - HOME_PAD * 2), h: Math.max(200, h - HOME_PAD * 2) };
  }

  // Uniform zoom: scale panel sizes and positions around the viewport center.
  function applyZoom(positions, sizes, zoom, avail) {
    if (zoom === 1) return { positions, sizes };
    const cx = HOME_PAD + avail.w / 2, cy = HOME_PAD + avail.h / 2;
    const p2 = new Map(), s2 = new Map();
    positions.forEach((p, id) => p2.set(id, { x: cx + (p.x - cx) * zoom, y: cy + (p.y - cy) * zoom }));
    sizes.forEach((s, id) => s2.set(id, { w: s.w * zoom, h: s.h * zoom }));
    return { positions: p2, sizes: s2 };
  }

  /* ── layout engines (each returns {positions: Map<id,{x,y}>, sizes: Map<id,{w,h}>}) ──
     Sizing policy: larger readable panels + scrolling over tiny panels.
       minW/minH = readable floor; prefW/prefH = comfortable preferred size.
     Only Compact mode may use smaller panels; Custom preserves user sizes. */
  function workflowLayout(nodes, avail, S) {
    const positions = new Map(), sizes = new Map();
    if (!nodes.length) return { positions, sizes };
    const xs = nodes.map((n) => n.x || 0), ys = nodes.map((n) => n.y || 0);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = Math.max(1, maxX - minX), spanY = Math.max(1, maxY - minY);
    const scale = Math.min(1, avail.w / spanX, avail.h / spanY);
    const ox = HOME_PAD + (avail.w - spanX * scale) / 2;
    const oy = HOME_PAD + (avail.h - spanY * scale) / 2;
    nodes.forEach((n) => {
      positions.set(n.id, { x: ox + ((n.x || 0) - minX) * scale, y: oy + ((n.y || 0) - minY) * scale });
      sizes.set(n.id, { w: S.minW, h: S.minH });   // sensible readable default
    });
    return { positions, sizes };
  }

  function gridLayout(nodes, edges, avail, S, gap) {
    const order = workflowOrder(nodes, edges);
    const positions = new Map(), sizes = new Map();
    const n = order.length;
    if (!n) return { positions, sizes };
    // responsive columns: as many as fit at the readable minimum width,
    // never creating tiny columns.
    const cols = Math.max(1, Math.min(n, Math.floor((avail.w + gap) / (S.minW + gap))));
    const rows = Math.ceil(n / cols);
    // panels expand to fill each column, up to the preferred width
    const pw = clamp((avail.w - (cols - 1) * gap) / cols, S.minW, S.prefW);
    const ph = S.prefH;
    const totalW = cols * pw + (cols - 1) * gap;
    const totalH = rows * ph + (rows - 1) * gap;
    const ox = HOME_PAD + (avail.w - totalW) / 2;
    const oy = HOME_PAD + Math.max(0, (avail.h - totalH) / 2);
    order.forEach((id, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      positions.set(id, { x: ox + col * (pw + gap) + pw / 2, y: oy + row * (ph + gap) + ph / 2 });
      sizes.set(id, { w: pw, h: ph });
    });
    return { positions, sizes };
  }

  function horizontalLayout(nodes, edges, avail, S, gap) {
    const order = workflowOrder(nodes, edges);
    const positions = new Map(), sizes = new Map();
    const n = order.length;
    if (!n) return { positions, sizes };
    // fixed readable size — never shrink to fit; overflow scrolls horizontally
    const pw = S.prefW, ph = S.prefH;
    const ox = HOME_PAD;
    const oy = HOME_PAD + avail.h / 2;
    order.forEach((id, i) => {
      positions.set(id, { x: ox + i * (pw + gap) + pw / 2, y: oy });
      sizes.set(id, { w: pw, h: ph });
    });
    return { positions, sizes };
  }

  function verticalLayout(nodes, edges, avail, S, gap) {
    const order = workflowOrder(nodes, edges);
    const positions = new Map(), sizes = new Map();
    const n = order.length;
    if (!n) return { positions, sizes };
    // one column that uses (nearly) the full available Home width
    const pw = avail.w;
    const ph = S.prefH;
    const ox = HOME_PAD + avail.w / 2;
    const totalH = n * ph + (n - 1) * gap;
    const oy = HOME_PAD + Math.max(0, (avail.h - totalH) / 2);
    order.forEach((id, i) => {
      positions.set(id, { x: ox, y: oy + i * (ph + gap) + ph / 2 });
      sizes.set(id, { w: pw, h: ph });
    });
    return { positions, sizes };
  }

  function customLayout(nodes, avail, custom, S) {
    const base = workflowLayout(nodes, avail, S);
    const positions = new Map(), sizes = new Map();
    nodes.forEach((n) => {
      const c = (custom && custom[n.id]) || null;
      if (c && Number.isFinite(c.x) && Number.isFinite(c.y)) positions.set(n.id, { x: c.x, y: c.y });
      else positions.set(n.id, base.positions.get(n.id));
      if (c && Number.isFinite(c.w) && Number.isFinite(c.h)) sizes.set(n.id, { w: clamp(c.w, 120, avail.w), h: clamp(c.h, 80, avail.h) });
      else sizes.set(n.id, base.sizes.get(n.id));
    });
    return { positions, sizes };
  }

  function computeLayout(nodes, edges, layout) {
    const avail = homeAvail();
    const mode = layout.mode || "workflow";
    const zoom = clamp(layout.zoom || 1, HOME_ZOOM_MIN, HOME_ZOOM_MAX);
    const S = panelSizes();
    let out;
    if (mode === "grid") out = gridLayout(nodes, edges, avail, S, HOME_GAP);
    else if (mode === "horizontal") out = horizontalLayout(nodes, edges, avail, S, HOME_GAP);
    else if (mode === "vertical") out = verticalLayout(nodes, edges, avail, S, HOME_GAP);
    else if (mode === "compact") out = gridLayout(nodes, edges, avail,
      { minW: S.compactW, prefW: S.compactW, minH: S.compactH, prefH: S.compactH }, 6);
    else if (mode === "custom") return customLayout(nodes, avail, layout.custom, S);
    else out = workflowLayout(nodes, avail, S);
    return applyZoom(out.positions, out.sizes, zoom, avail);
  }

  /* ── Home layout persistence (localStorage, keyed by workflow id) ── */
  function loadHomeLayouts() {
    try {
      const raw = window.localStorage.getItem(HOME_LAYOUT_KEY);
      Ag.homeLayouts = raw ? (JSON.parse(raw) || {}) : {};
    } catch (_) { Ag.homeLayouts = {}; }
    try {
      const mode = window.localStorage.getItem(HOME_MODE_KEY);
      if (HOME_LAYOUTS.includes(mode)) Ag.homeMode = mode;
    } catch (_) { /* keep default */ }
  }
  function saveHomeLayouts() {
    try { window.localStorage.setItem(HOME_LAYOUT_KEY, JSON.stringify(Ag.homeLayouts || {})); } catch (_) { /* blocked */ }
    try { window.localStorage.setItem(HOME_MODE_KEY, Ag.homeMode); } catch (_) { /* blocked */ }
  }
  function currentWorkflowId() { return Ag.homeWorkflow ? Ag.homeWorkflow.id : null; }
  function currentHomeLayout() {
    const wfId = currentWorkflowId();
    const saved = (wfId && Ag.homeLayouts && Ag.homeLayouts[wfId]) || null;
    return {
      mode: (saved && saved.mode && HOME_LAYOUTS.includes(saved.mode)) ? saved.mode : (Ag.homeMode || "workflow"),
      zoom: clamp((saved && saved.zoom) || Ag.homeZoom || 1, HOME_ZOOM_MIN, HOME_ZOOM_MAX),
      custom: (saved && saved.custom) || {},
    };
  }
  function updateHomeLayout(layout) {
    const wfId = currentWorkflowId();
    if (wfId) {
      if (!Ag.homeLayouts) Ag.homeLayouts = {};
      const cur = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
      cur.mode = layout.mode;
      cur.zoom = layout.zoom;
      if (layout.custom) cur.custom = layout.custom;
    }
    Ag.homeMode = layout.mode;
    Ag.homeZoom = layout.zoom;
    saveHomeLayouts();
  }

  function setHomeLayout(mode) {
    if (!HOME_LAYOUTS.includes(mode)) return;
    const layout = currentHomeLayout();
    layout.mode = mode;
    updateHomeLayout(layout);
    buildWorkspace();
  }
  function setHomeZoom(zoom) {
    const layout = currentHomeLayout();
    layout.zoom = clamp(zoom, HOME_ZOOM_MIN, HOME_ZOOM_MAX);
    updateHomeLayout(layout);
    buildWorkspace();
  }
  function resetHomeLayout() {
    const wfId = currentWorkflowId();
    // Discard custom positions/sizes, then return to the *selected default*
    // mode (Ag.homeMode). A manual drag/resize auto-switches to Custom without
    // changing Ag.homeMode, so Reset returns the user to their chosen layout.
    const defaultMode = (Ag.homeMode && HOME_LAYOUTS.includes(Ag.homeMode)) ? Ag.homeMode : "workflow";
    if (wfId && Ag.homeLayouts) {
      const layout = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
      layout.custom = {};
      layout.zoom = 1;
      layout.mode = defaultMode;
    }
    Ag.homeZoom = 1;
    saveHomeLayouts();
    buildWorkspace();
  }
  function updateHomeLayoutUi() {
    const sel = $("#home-layout-select");
    const layout = currentHomeLayout();
    if (sel) sel.value = layout.mode;
    const label = $("#home-zoom-label");
    if (label) label.textContent = Math.round(layout.zoom * 100) + "%";
  }

  /* ── shared renderer: panels + edges for any layout mode ── */
  function renderHomeGraph(wg, nodes, edges, positions, sizes, mode) {
    wg.classList.add("workflow-mode");
    wg.classList.toggle("custom-mode", mode === "custom");
    nodes.forEach((n) => {
      const a = Ag.agents.find((x) => x.agent === n.agent);
      const view = {
        tag: a ? a.tag : (n.agent || "node"),
        name: n.label || (a ? a.name : n.agent),
        model: n.resolved_model || n.model || "",
        status: "idle",
        progress: 0,
        token_usage: 0,
        running: false,
        prompt: "",
      };
      const card = panelFor(view, { nodeId: n.id, noStop: true });
      const p = positions.get(n.id) || { x: HOME_PAD, y: HOME_PAD };
      const s = sizes.get(n.id) || { w: 280, h: 200 };
      card.style.position = "absolute";
      card.style.width = s.w + "px";
      card.style.height = s.h + "px";
      card.style.left = p.x + "px";
      card.style.top = p.y + "px";
      card.style.transform = "translate(-50%, -50%)";
      wg.appendChild(card);
      // node-aware console: replay this node's own session (independent per
      // workflow node id — duplicate agents never share output), merged with
      // the agent's live SSE session (Ag.sessions[tag]) so terminal-dispatch
      // output survives workspace rebuilds. De-duplicated by backend seq "n".
      const nodeSess = (Ag.nodeSessions ? Ag.nodeSessions[n.id] : null) || [];
      const agentSess = (view.tag && Ag.sessions && Ag.sessions[view.tag]) || [];
      const seen = new Set();
      const merged = [];
      for (const ev of nodeSess.concat(agentSess)) {
        if (ev.n !== undefined) {
          if (seen.has(ev.n)) continue;
          seen.add(ev.n);
        }
        merged.push(ev);
      }
      merged.forEach((ev) => {
        if (PANEL_KINDS.includes(ev.kind)) {
          appendEv(card.querySelector(".p-console"), ev);
        }
      });
      // node-aware run status (from the active workflow run, keyed by node id)
      const st = Ag.runStatuses ? Ag.runStatuses[n.id] : undefined;
      if (st) setPanelRunStatus(card, st);
    });
    drawHomeEdges(wg, edges, positions, sizes);
    bindPanelInteractions(wg);
  }

  function drawHomeEdges(wg, edges, positions, sizes) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "home-edges");
    // Size the SVG to the full content extent so edges stay aligned when the
    // workspace scrolls (horizontal/vertical/custom layouts can overflow).
    let extW = 0, extH = 0;
    positions.forEach((p, id) => {
      const s = (sizes && sizes.get(id)) || { w: 0, h: 0 };
      extW = Math.max(extW, p.x + s.w / 2);
      extH = Math.max(extH, p.y + s.h / 2);
    });
    svg.style.width = Math.max(extW, 1) + "px";
    svg.style.height = Math.max(extH, 1) + "px";
    (edges || []).forEach((e) => {
      const a = positions.get(e.source), b = positions.get(e.target);
      if (!a || !b) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
      line.setAttribute("class", "home-edge");
      // edges reference workflow NODE ids (not agent tags)
      line.setAttribute("data-source", e.source);
      line.setAttribute("data-target", e.target);
      if (e.condition) line.setAttribute("data-condition", e.condition);
      svg.appendChild(line);
    });
    wg.appendChild(svg);
  }

  function panelCenter(nodeId) {
    const card = $(`.panel[data-workflow-node-id="${nodeId}"]`);
    if (!card) return null;
    return { x: parseFloat(card.style.left), y: parseFloat(card.style.top) };
  }
  function redrawHomeEdges() {
    const wg = $("#workspace-grid");
    if (!wg) return;
    let svg = null;
    for (const c of wg.children || []) {
      if (String(c.className).includes("home-edges")) svg = c;
    }
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    let extW = 0, extH = 0;
    (Ag.homeEdges || []).forEach((e) => {
      const a = panelCenter(e.source), b = panelCenter(e.target);
      if (!a || !b) return;
      extW = Math.max(extW, a.x, b.x);
      extH = Math.max(extH, a.y, b.y);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
      line.setAttribute("class", "home-edge");
      line.setAttribute("data-source", e.source);
      line.setAttribute("data-target", e.target);
      if (e.condition) line.setAttribute("data-condition", e.condition);
      svg.appendChild(line);
    });
    svg.style.width = Math.max(extW, 1) + "px";
    svg.style.height = Math.max(extH, 1) + "px";
  }

  /* ── Home panel drag + resize (visual layer, persisted per workflow) ── */
  function customNodeBase(nodeId) {
    const c = (currentHomeLayout().custom || {})[nodeId];
    return c || null;
  }

  /* A manual drag/resize promotes the layout to Custom: snapshot every
     rendered panel's current position/size into the per-workflow layout, then
     switch the effective mode to Custom WITHOUT touching the user's selected
     default (Ag.homeMode) so Reset Layout can revert to it. Idempotent — once
     Custom, subsequent moves update only the one node. */
  function switchToCustom() {
    const wfId = currentWorkflowId();
    if (!wfId) return;
    if (currentHomeLayout().mode === "custom") return;
    if (!Ag.homeLayouts) Ag.homeLayouts = {};
    const layout = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
    if (!layout.custom) layout.custom = {};
    $$(".panel[data-workflow-node-id]").forEach((card) => {
      const id = card.dataset.workflowNodeId;
      const x = parseFloat(card.style.left), y = parseFloat(card.style.top);
      const w = parseFloat(card.style.width), h = parseFloat(card.style.height);
      if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(w) && Number.isFinite(h)) {
        layout.custom[id] = { x: x, y: y, w: w, h: h };
      }
    });
    layout.mode = "custom";
    saveHomeLayouts();
    updateHomeLayoutUi();
    const wg = $("#workspace-grid");
    if (wg) wg.classList.add("custom-mode");
  }

  /* Keep a dragged panel's top-left corner on the workspace (center ≥ half-size)
     so it can't be lost off the top/left. Positive overflow is allowed because
     horizontal/vertical/custom layouts scroll instead of clipping. */
  function clampToWorkspace(x, y, w, h) {
    return { x: Math.max(x, w / 2), y: Math.max(y, h / 2) };
  }

  function moveNode(nodeId, x, y) {
    switchToCustom();
    const card = $(`.panel[data-workflow-node-id="${nodeId}"]`);
    const w = card ? (parseFloat(card.style.width) || 280) : 280;
    const h = card ? (parseFloat(card.style.height) || 200) : 200;
    const p = clampToWorkspace(x, y, w, h);
    const wfId = currentWorkflowId();
    if (wfId && Ag.homeLayouts) {
      const layout = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
      if (!layout.custom) layout.custom = {};
      const cur = layout.custom[nodeId] || {};
      layout.custom[nodeId] = { x: p.x, y: p.y, w: cur.w, h: cur.h };
    }
    if (card) { card.style.left = p.x + "px"; card.style.top = p.y + "px"; }
    saveHomeLayouts();
    redrawHomeEdges();
  }
  function resizeNode(nodeId, w, h) {
    switchToCustom();
    const S = panelSizes();
    const avail = homeAvail();
    // interactive resize floor: readable minimums; ceiling: the workspace size.
    const minW = S.resizeMinW, minH = S.resizeMinH;
    const maxW = Math.max(minW, avail.w), maxH = Math.max(minH, avail.h);
    const wc = clamp(w, minW, maxW), hc = clamp(h, minH, maxH);
    const wfId = currentWorkflowId();
    if (wfId && Ag.homeLayouts) {
      const layout = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
      if (!layout.custom) layout.custom = {};
      const cur = layout.custom[nodeId] || {};
      layout.custom[nodeId] = { x: cur.x, y: cur.y, w: wc, h: hc };
    }
    const card = $(`.panel[data-workflow-node-id="${nodeId}"]`);
    if (card) { card.style.width = wc + "px"; card.style.height = hc + "px"; }
    saveHomeLayouts();
    redrawHomeEdges();
  }
  /* Directional (edge/corner) resize: each handle names which edges move.
     The opposite edge stays fixed (normal desktop-window semantics), so the
     center follows by half the applied delta; size is clamped to the readable
     floor and the workspace ceiling, and the top-left stays on the workspace. */
  function resizeNodeDelta(nodeId, dir, dx, dy) {
    const edges = RESIZE_EDGES[dir];
    if (!edges) return;
    switchToCustom();
    const card = $(`.panel[data-workflow-node-id="${nodeId}"]`);
    if (!card) return;
    const w0 = parseFloat(card.style.width) || 280;
    const h0 = parseFloat(card.style.height) || 200;
    const cx0 = parseFloat(card.style.left) || 0;
    const cy0 = parseFloat(card.style.top) || 0;
    const S = panelSizes();
    const avail = homeAvail();
    const minW = S.resizeMinW, minH = S.resizeMinH;
    const maxW = Math.max(minW, avail.w), maxH = Math.max(minH, avail.h);
    let w = w0, h = h0;
    if (edges.h === "e") w = w0 + dx;
    if (edges.h === "w") w = w0 - dx;
    if (edges.v === "s") h = h0 + dy;
    if (edges.v === "n") h = h0 - dy;
    let wc = clamp(w, minW, maxW), hc = clamp(h, minH, maxH);
    // A leading (top/left) edge must not cross the workspace origin: clamp the
    // growth so the moving edge stops at 0 while the fixed edge stays put. The
    // trailing (bottom/right) edges may overflow — the workspace scrolls.
    if (edges.h === "w") wc = Math.min(wc, cx0 + w0 / 2);
    if (edges.v === "n") hc = Math.min(hc, cy0 + h0 / 2);
    // Recompute the center from the fixed edge(s): dragging the left/top edge
    // moves the opposite (fixed) edge's position, so the center follows by
    // half the applied width/height delta.
    let cx = cx0, cy = cy0;
    if (edges.h === "e") cx = cx0 + (wc - w0) / 2;
    if (edges.h === "w") cx = cx0 + (w0 - wc) / 2;
    if (edges.v === "s") cy = cy0 + (hc - h0) / 2;
    if (edges.v === "n") cy = cy0 + (h0 - hc) / 2;
    const p = { x: cx, y: cy };
    const wfId = currentWorkflowId();
    if (wfId && Ag.homeLayouts) {
      const layout = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
      if (!layout.custom) layout.custom = {};
      layout.custom[nodeId] = { x: p.x, y: p.y, w: wc, h: hc };
    }
    card.style.left = p.x + "px";
    card.style.top = p.y + "px";
    card.style.width = wc + "px";
    card.style.height = hc + "px";
    saveHomeLayouts();
    redrawHomeEdges();
  }
  function setCustomNode(nodeId, patch) {
    const wfId = currentWorkflowId();
    if (!wfId) return;
    if (!Ag.homeLayouts) Ag.homeLayouts = {};
    const layout = Ag.homeLayouts[wfId] || (Ag.homeLayouts[wfId] = {});
    if (!layout.custom) layout.custom = {};
    const cur = layout.custom[nodeId] || {};
    const avail = homeAvail();
    layout.custom[nodeId] = {
      x: Number.isFinite(patch.x) ? patch.x : cur.x,
      y: Number.isFinite(patch.y) ? patch.y : cur.y,
      w: Number.isFinite(patch.w) ? clamp(patch.w, 120, avail.w) : cur.w,
      h: Number.isFinite(patch.h) ? clamp(patch.h, 80, avail.h) : cur.h,
    };
    saveHomeLayouts();
    buildWorkspace();
  }
  function commitCustomLayout() { saveHomeLayouts(); }

  function bringToFront(card) {
    // stay above the edge SVG (z-index 1) and sibling panels (z-index 2)
    card.style.zIndex = ++Ag.homeZTop + 2;
    card.classList.add("active");
  }

  function bindPanelInteractions(wg) {
    $$(".panel[data-workflow-node-id]").forEach((card) => {
      const nodeId = card.dataset.workflowNodeId;
      if (!nodeId || card.dataset.panelBound) return;
      card.dataset.panelBound = "1";
      // 8 resize handles: every edge + corner, each carrying its direction.
      if (!card.querySelector(".panel-resize")) {
        RESIZE_DIRS.forEach((dir) => {
          const handle = el("div", "panel-resize r-" + dir);
          handle.dataset.dir = dir;
          card.appendChild(handle);
        });
      }
      const head = card.querySelector(".p-head");
      const start = (ev, dir) => {
        if (ev.button !== 0) return;   // primary button only
        // never start a drag from an interactive control inside the panel
        if (!dir && ev.target && ev.target.closest &&
            ev.target.closest("button, input, select, textarea, a, .p-console, .p-status, .panel-resize")) return;
        ev.preventDefault();
        ev.stopPropagation();
        switchToCustom();          // manual move/resize → Custom (visual layer only)
        bringToFront(card);
        card.classList.add("dragging");
        const sx = ev.clientX, sy = ev.clientY;
        const startX = parseFloat(card.style.left), startY = parseFloat(card.style.top);
        const move = (e) => {
          const dx = e.clientX - sx, dy = e.clientY - sy;
          if (dir) resizeNodeDelta(nodeId, dir, dx, dy);
          else moveNode(nodeId, startX + dx, startY + dy);
        };
        const up = () => {
          card.classList.remove("dragging");
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          commitCustomLayout();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      };
      if (head) head.addEventListener("pointerdown", (ev) => start(ev, null));
      Array.from(card.querySelectorAll(".panel-resize")).forEach((handle) => {
        handle.addEventListener("pointerdown", (ev) => start(ev, handle.dataset.dir));
      });
    });
  }

  function buildWorkspace() {
    const wg = $("#workspace-grid");
    empty(wg);
    wg.classList.remove("workflow-mode", "custom-mode");
    wg.style.gridTemplateColumns = "";
    wg.style.gridTemplateRows = "";
    // The active workflow is the single source of truth for the Home agent
    // windows. When one is active, Home renders it through the selected layout
    // mode; otherwise Home shows an empty workflow state — it never falls back
    // to the global registry / agents_visible layout.
    if (!Ag.homeWorkflow) {
      wg.appendChild(el("div", "workspace-empty",
        "No active workflow — Create or activate a workflow to start."));
      updateHomeLayoutUi();
      return;
    }
    const nodes = enabledNodes();
    const edges = Ag.homeEdges || [];
    const layout = currentHomeLayout();
    const { positions, sizes } = computeLayout(nodes, edges, layout);
    renderHomeGraph(wg, nodes, edges, positions, sizes, layout.mode);
    updateHomeLayoutUi();
  }

  /* ── back-compat entry: force the Workflow (designer-graph) layout ── */
  function buildWorkflowWorkspace(wg) {
    wg = wg || $("#workspace-grid");
    empty(wg);
    wg.classList.remove("custom-mode");
    const nodes = enabledNodes();
    const edges = Ag.homeEdges || [];
    const { positions, sizes } = workflowLayout(nodes, homeAvail());
    renderHomeGraph(wg, nodes, edges, positions, sizes, "workflow");
  }

  function runStatusToUi(st) {
    if (st === "running") return "thinking";
    if (st === "completed") return "active";
    if (st === "failed") return "error";
    return "idle";
  }

  function setActiveNode(nodeId) {
    Ag.activeNodeId = nodeId;
    $$(".panel").forEach((card) =>
      card.classList.toggle("active", card.dataset.workflowNodeId === nodeId));
    const n = Ag.homeNodes.find((x) => x.id === nodeId);
    const elTarget = $("#send-target");
    if (elTarget) elTarget.textContent = n ? (n.label || n.agent) : nodeId;
  }

  function nodeEvent(nodeId, ev) {
    // Node-aware session persistence: workflow node id, not agent tag.
    const sess = (Ag.nodeSessions[nodeId] = Ag.nodeSessions[nodeId] || []);
    sess.push(ev);
    if (sess.length > 400) sess.splice(0, sess.length - 400);
    const card = $(`.panel[data-workflow-node-id="${nodeId}"]`);
    if (card && PANEL_KINDS.includes(ev.kind)) {
      appendEv(card.querySelector(".p-console"), ev);
    }
  }

  async function pollActiveRun() {
    if (!Ag.activeRunId) return;
    let snap;
    try { snap = await api(`/api/workflows/runs/${Ag.activeRunId}`); } catch (_) { return; }
    Ag.runStatuses = snap.statuses || {};
    const em = (Ag.runEmitted[Ag.activeRunId] = Ag.runEmitted[Ag.activeRunId] || {});
    Object.entries(snap.outputs || {}).forEach(([nid, text]) => {
      if (!text || em[nid]) return;
      const st = (snap.statuses || {})[nid];
      if (st === "completed" || st === "failed") {
        em[nid] = true;
        nodeEvent(nid, { kind: "line", text });
      }
    });
    Object.entries(Ag.runStatuses).forEach(([nid, st]) => {
      const card = $(`.panel[data-workflow-node-id="${nid}"]`);
      if (!card) return;
      setPanelRunStatus(card, st);
      card.classList.toggle("running", st === "running");
    });
    if (snap.finished) Ag.activeRunId = null;
  }

  function setActive(tag) {
    Ag.activeTag = tag;
    Ag.prefs.active_tag = tag;
    $$(".panel").forEach((card) => card.classList.toggle("active", card.dataset.tag === tag));
    $("#send-target").textContent = tagName(tag);
    savePrefs();
  }

  function tagName(tag) {
    const a = Ag.agents.find((x) => x.tag === tag);
    return a ? `${tag.toUpperCase()} · ${a.name}` : tag || "—";
  }

  function panelEl(tag) { return $(`.panel[data-tag="${tag}"]`); }

  function appendEv(consoleEl, ev) {
    const nearBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 40;
    const row = el("div", "ev " + (ev.kind || "line"));
    row.textContent = ev.text || "";
    // Hover timestamp (non-intrusive; the text itself stays verbatim).
    try { row.title = new Date().toLocaleTimeString(); } catch (_) { /* no Date */ }
    consoleEl.appendChild(row);
    if (nearBottom) consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  function onAgentEvent(tag, ev) {
    // 1) Persist FIRST — a valid Agent event must never be lost just because
    //    its panel is not currently rendered. Ag.sessions[tag] is the single
    //    source of truth for workspace rebuilds; events are kept in arrival
    //    order and de-duplicated against the init snapshot by backend seq "n".
    const sess = (Ag.sessions[tag] = Ag.sessions[tag] || []);
    const seen = sess.some((e) => e.n !== undefined && e.n === ev.n);
    if (!seen) {
      sess.push(ev);
      if (sess.length > SESSION_TAIL) sess.splice(0, sess.length - SESSION_TAIL);
    }
    // 2) Render immediately when a panel exists; otherwise the event stays in
    //    Ag.sessions[tag] and is rendered when the agent becomes visible.
    const card = panelEl(tag);
    if (!card) return;
    if (ev.kind === "status") {
      const label = card.querySelector(".p-status-label");
      if (label) label.textContent = STATUS_LABEL[ev.text] || ev.text;
      card.querySelector(".p-status").className = "p-status " + statusCls(ev.text);
    }
    if (ev.kind === "run") {
      card.querySelector(".p-task").textContent = ev.text.split("::")[1] || ev.text;
      card.querySelector(".p-task").title = ev.text;
    }
    if (PANEL_KINDS.includes(ev.kind) && !seen) {
      // skip the append when this event was already replayed from the init
      // snapshot — session and DOM must not disagree on page-load-during-run
      appendEv(card.querySelector(".p-console"), ev);
    }
  }

  /* ─────────────────────── status table ──────────────────────── */
  function buildStatusTable() {
    const tbody = $("#status-table tbody");
    empty(tbody);
    Ag.agents.forEach((a) => {
      const tr = el("tr");
      tr.dataset.tag = a.tag;
      const cells = { status: el("td"), bar: el("td"), toks: el("td"), task: el("td") };
      tr.appendChild(el("td", null, `${a.tag.toUpperCase()} · ${a.name}`));
      cells.status.appendChild(el("span", "dot"));
      cells.status.appendChild(el("span", "st-label", a.status));
      const barWrap = el("div", "status-bar");
      cells.bar.appendChild(barWrap);
      tr.appendChild(cells.status);
      tr.appendChild(cells.bar);
      tr.appendChild(cells.toks);
      cells.task.className = "task";
      tr.appendChild(cells.task);
      tbody.appendChild(tr);
      let fill = null;
      cells.bar.querySelector(".status-bar").appendChild(fill = el("div", "fill"));
      updateStatusRow(a, cells, fill);
    });
  }

  function updateStatusRow(a, cells, fill) {
    if (!fill) return; // no-op for live events
    cells.status.querySelector(".st-label").textContent = a.status;
    cells.status.className = "status-cell " + statusCls(a.status);
    fill.style.width = (a.progress || 0) + "%";
    cells.toks.textContent = (a.token_usage || 0) + "%";
    cells.task.textContent = (a.prompt || "").slice(0, 140);
  }

  function syncStatusRow(tag, st, progress, toks, prompt) {
    const tr = document.querySelector(`#status-table tr[data-tag="${tag}"]`);
    if (!tr) return;
    if (st !== undefined) {
      tr.querySelector(".st-label").textContent = st;
      tr.querySelector(".status-cell").className = "status-cell " + statusCls(st);
    }
    if (progress !== undefined && tr.querySelector(".fill")) {
      tr.querySelector(".fill").style.width = progress + "%";
    }
    if (toks !== undefined) tr.querySelectorAll("td")[2].textContent = toks + "%";
    if (prompt !== undefined) tr.querySelectorAll("td")[3].textContent = prompt.slice(0, 140);
  }

  /* ─────────────────────── graph view (Phase 24) ─────────────── */
  let graphEls = {
    svg: null, world: null, nodes: new Map(), edges: new Map(), byName: {},
    sectionHubs: {}, planeH: 440, bounds: null, layoutSig: null, cachedPos: [], mmRaf: null,
  };
  // Per-node settled positions (name -> {x,y}), persisted across renders so a
  // re-render or a visibility/topology change never moves an unchanged node.
  const graphPosCache = {};
  const GraphView = { scale: 1, tx: 0, ty: 0, atFit: true };
  const panState = { active: false, pid: null, px: 0, py: 0, moved: false };
  const GP = window.GraphMath;

  const _canvas = () => $("#graph-svg");
  const _rect = () => _canvas().getBoundingClientRect();
  function nodeByName(name) {
    return Ag.view.nodes.find((nd) => nd.name === name);
  }

  // Map a canvas client point into viewBox plane coords (uniform scale).
  function planePos(clientX, clientY) {
    const r = _rect();
    return {
      x: (clientX - r.left) * 760 / Math.max(1, r.width),
      y: (clientY - r.top) * graphEls.planeH / Math.max(1, r.height),
    };
  }

  function syncViewBox() {
    const svg = graphEls.svg;
    if (!svg) return;
    const w = Math.max(60, svg.clientWidth || 760);
    const h = Math.max(60, svg.clientHeight || 300);
    graphEls.planeH = Math.min(1000, Math.max(300, Math.round(760 * h / w)));
    svg.setAttribute("viewBox", `0 0 760 ${graphEls.planeH}`);
    _canvas().classList.toggle("narrow", w < 200);
    const mm = $("#graph-minimap");
    if (mm) mm.classList.toggle("hidden", w < 200 || Ag.graph.nodes.length === 0 || Ag.prefs.minimap_on === false);
  }

  function currentBand() { return GP.bandForZoom(GraphView.scale); }

  function applyBand() {
    const band = currentBand();
    const canvas = _canvas();
    if (canvas.dataset.band === band) return;
    canvas.dataset.band = band;
    graphEls.nodes.forEach((g) => {
      const nd = nodeByName(g.dataset.name);
      if (!nd) return;
      // zoomed out: keep only the section hubs / root spine visible
      g.style.display =
        (band === "out" && !graphEls.sectionHubs[nd.name]) ? "none" : "";
      const r = GP.radiusFor(nd, band);
      const circ = g.querySelector(".g-circle");
      if (circ) circ.setAttribute("r", r);
      const lbl = g.querySelector(".g-label");
      if (lbl) {
        // at zoom-out the visible set is the section-hub spine, so labels
        // follow that same set (not just the degree ≥ 10 rule)
        const show = band === "out"
          ? !!graphEls.sectionHubs[nd.name]
          : GP.labelVisibleFor(nd, band);
        lbl.classList.toggle("hidden", !show);
        lbl.setAttribute("y", GP.labelYOffset(r, band));
      }
    });
    // LOD edge culling: hide edges the current band does not show
    graphEls.edges.forEach((grp, key) => {
      const p = key.split("|");
      const show = GP.edgeVisibleFor(p, band, graphEls.byName, graphEls.sectionHubs);
      grp.style.display = show ? "" : "none";
    });
  }

  function applyGraphView() {
    const world = graphEls.world;
    if (!world) return;
    const cam = GP.panClamp(
      { scale: GraphView.scale, tx: GraphView.tx, ty: GraphView.ty },
      graphEls.bounds, 760, graphEls.planeH);
    GraphView.scale = cam.scale; GraphView.tx = cam.tx; GraphView.ty = cam.ty;
    world.setAttribute("transform", `translate(${GraphView.tx},${GraphView.ty}) scale(${GraphView.scale})`);
    const inv = 1 / GraphView.scale;
    graphEls.nodes.forEach((g) => {
      const lbl = g.querySelector(".g-label");
      if (lbl) lbl.setAttribute("transform", `scale(${inv})`);
    });
    applyBand();
    scheduleMinimap();
  }

  function zoomBy(factor, px, py) {
    if (px === undefined) { px = 380; py = graphEls.planeH / 2; }   // viewBox center
    const cam = GP.zoomAtPoint(
      { scale: GraphView.scale, tx: GraphView.tx, ty: GraphView.ty },
      px, py, factor, 760, graphEls.planeH);
    GraphView.scale = cam.scale; GraphView.tx = cam.tx; GraphView.ty = cam.ty;
    GraphView.atFit = false;
    applyGraphView();
  }

  function fitGraph() {
    syncViewBox();
    const cam = GP.fitCamera(graphEls.bounds, 760, graphEls.planeH, 42);
    GraphView.scale = cam.scale; GraphView.tx = cam.tx; GraphView.ty = cam.ty;
    GraphView.atFit = true;
    applyGraphView();
  }

  function resetGraphView() { fitGraph(); }

  function layoutGraph(nodes, edges) {
    // Stable incremental layout: nodes that already have a settled position
    // keep it (pinned + seeded), so a re-render or a visibility/topology
    // change never moves an unchanged node. Only nodes new to the graph relax.
    const fixed = {};
    nodes.forEach((nd) => { if (graphPosCache[nd.name]) fixed[nd.name] = true; });
    GP.runLayout(nodes, edges, { iterations: 500, seed: graphPosCache, fixed: fixed });
    nodes.forEach((nd) => { graphPosCache[nd.name] = { x: nd.x, y: nd.y }; });
  }

  function renderGraph() {
    const host = $("#graph-stage");
    empty(host);
    const nodes = Ag.view.nodes;
    const edges = Ag.view.edges;
    if (!nodes.length) {
      host.appendChild(el("div", "placeholder", "no vault nodes"));
      buildLegend();
      return;
    }
    layoutGraph(nodes, edges);
    graphEls.bounds = GP.worldBounds(nodes);

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    const world = document.createElementNS(svgNS, "g");
    world.setAttribute("class", "graph-world");
    svg.appendChild(world);

    const byName = {};
    nodes.forEach((nd) => (byName[nd.name] = nd));
    graphEls.byName = byName;
    graphEls.sectionHubs = GP.sectionHubNames(nodes);

    edges.forEach((pair) => {
      const a = byName[pair[0]], b = byName[pair[1]];
      if (!a || !b) return;
      // vault links are reciprocal — draw each adjacency once
      const key = pair[0] < pair[1] ? pair[0] + "|" + pair[1] : pair[1] + "|" + pair[0];
      if (graphEls.edges.has(key)) return;
      const grp = document.createElementNS(svgNS, "g");
      const hit = document.createElementNS(svgNS, "line");
      hit.setAttribute("class", "g-hit");
      const line = document.createElementNS(svgNS, "line");
      line.setAttribute("class", "g-edge");
      [hit, line].forEach((l) => {
        l.setAttribute("data-a", pair[0]);
        l.setAttribute("data-b", pair[1]);
        l.setAttribute("x1", a.x); l.setAttribute("y1", a.y);
        l.setAttribute("x2", b.x); l.setAttribute("y2", b.y);
      });
      grp.appendChild(hit);
      grp.appendChild(line);
      world.appendChild(grp);
      graphEls.edges.set(key, grp);
    });

    nodes.forEach((nd) => {
      const g = document.createElementNS(svgNS, "g");
      g.setAttribute("class", "g-node " + typeCls(nd));
      g.setAttribute("data-name", nd.name);
      g.setAttribute("transform", `translate(${nd.x},${nd.y})`);
      const circ = document.createElementNS(svgNS, "circle");
      circ.setAttribute("class", "g-circle");
      circ.setAttribute("fill",
        FOLDER_COLOR[nd.folder] === "var(--folder-root)" ? "#e6edf3" : FOLDER_COLOR[nd.folder] || "#888");
      g.appendChild(circ);
      const glyph = glyphFor(nd);
      if (glyph) g.appendChild(glyph);
      const lbl = document.createElementNS(svgNS, "text");
      lbl.setAttribute("class", "g-label");
      lbl.setAttribute("text-anchor", "middle");
      const raw = nd.name.replace(/^Agent_/, "");
      lbl.textContent = raw.length > 18 ? raw.slice(0, 16) + "…" : raw;
      g.appendChild(lbl);
      world.appendChild(g);
      graphEls.nodes.set(nd.name, g);
    });
    graphEls.world = world;
    graphEls.svg = svg;
    host.appendChild(svg);
    _canvas().dataset.band = "";   // force band re-application on the new DOM
    syncViewBox();
    buildLegend();
    applyGraphSelection();
    fitGraph();
  }

  function lineOf(grp) { return grp ? grp.querySelector(".g-edge") : null; }

  function typeCls(nd) {
    const map = { agent: "n-agent", component: "n-component", system: "n-system",
                  task: "n-task", architecture: "n-architecture",
                  documentation: "n-doc", decision: "n-decision", test: "n-test" };
    const cls = map[nd.type] || "n-unknown";
    const hub = nd.folder === "root" || (nd.degree || 0) >= GP.HUB_DEGREE ? " n-hub" : "";
    return cls + hub;
  }

  function glyphFor(nd) {
    const svgNS = "http://www.w3.org/2000/svg";
    if (nd.type !== "agent" && nd.type !== "component") return null;
    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", "g-glyph");
    if (nd.type === "agent") {
      const dot = document.createElementNS(svgNS, "circle");
      dot.setAttribute("r", 1.9);
      g.appendChild(dot);
    } else {
      const box = document.createElementNS(svgNS, "rect");
      box.setAttribute("x", -2.4); box.setAttribute("y", -2.4);
      box.setAttribute("width", 4.8); box.setAttribute("height", 4.8);
      box.setAttribute("rx", 0.8);
      g.appendChild(box);
    }
    return g;
  }

  function buildLegend() {
    const legend = $("#graph-legend");
    empty(legend);
    const present = new Set(Ag.graph.nodes.map((nd) => nd.folder));
    FOLDER_ORDER.filter((f) => present.has(f)).forEach((f) => {
      const item = el("span", "legend-item");
      const dot = el("span", "legend-dot");
      dot.style.background = FOLDER_COLOR[f] === "var(--folder-root)" ? "#e6edf3" : cssVar(FOLDER_COLOR[f]);
      item.appendChild(dot);
      item.appendChild(el("span", null, f === "root" ? "root" : f.slice(3)));
      legend.appendChild(item);
    });
  }

  /* ── Phase 24B: section filters + core/important view ──────────── */
  function folderLabel(f) { return f === "root" ? "Root" : f.slice(3); }

  function graphViewNodes() {
    return Ag.coreView
      ? GP.coreGraph(Ag.graph.nodes, Ag.graph.edges)
      : GP.applySectionFilter(Ag.graph.nodes, Ag.graph.edges, Ag.sectionFilter);
  }

  function buildGraphFilters() {
    const wrap = $("#graph-filters");
    if (!wrap) return;
    empty(wrap);
    const chip = (label, active, onClick, extraCls) => {
      const b = el("button", "f-chip" + (extraCls ? " " + extraCls : "") + (active ? " active" : ""));
      b.textContent = label;
      b.addEventListener("click", onClick);
      wrap.appendChild(b);
    };
    chip("All", !Ag.coreView && Ag.sectionFilter.length === 0, () => {
      Ag.coreView = false;
      Ag.sectionFilter = [];
      refreshGraphView();
    });
    chip("Core", Ag.coreView, () => {
      Ag.coreView = !Ag.coreView;
      if (Ag.coreView) Ag.sectionFilter = [];
      refreshGraphView();
    }, "core");
    GP.presentFolders(Ag.graph.nodes).forEach((f) => {
      const on = !Ag.coreView && Ag.sectionFilter.includes(f);
      chip(folderLabel(f), on, () => {
        if (Ag.coreView) Ag.coreView = false;
        const i = Ag.sectionFilter.indexOf(f);
        if (i >= 0) Ag.sectionFilter.splice(i, 1); else Ag.sectionFilter.push(f);
        refreshGraphView();
      });
    });
  }

  function refreshGraphView() {
    const sel = graphViewNodes();
    Ag.view.nodes = sel.nodes;
    Ag.view.edges = sel.edges;
    buildGraphFilters();
    renderGraph();
    const total = Ag.graph.nodes.length;
    $("#graph-count").textContent =
      sel.nodes.length + (sel.nodes.length === total ? "" : " / " + total) + " nodes";
  }

  function neighborSet(name) {
    const set = new Set([name]);
    Ag.view.edges.forEach((p) => {
      if (p[0] === name) set.add(p[1]);
      if (p[1] === name) set.add(p[0]);
    });
    return set;
  }

  function applyGraphSelection() {
    const sel = Ag.selectedNode;
    graphEls.nodes.forEach((g, name) => {
      g.classList.toggle("selected", name === sel);
      if (!sel) {
        g.classList.remove("dim");
        return;
      }
      g.classList.toggle("dim", !neighborSet(sel).has(name));
    });
    graphEls.edges.forEach((grp, key) => {
      const line = lineOf(grp);
      if (!line) return;
      if (!sel) { line.classList.remove("hot"); return; }
      const [a, b] = key.split("|");
      line.classList.toggle("hot", a === sel || b === sel);
    });
  }

  function setHover(name) {
    const nb = name ? neighborSet(name) : null;
    graphEls.nodes.forEach((g, k) => {
      g.classList.toggle("hover", k === name);
      g.classList.toggle("hover-nb", !!(name && nb.has(k) && k !== name));
    });
    graphEls.edges.forEach((grp, key) => {
      const line = lineOf(grp);
      if (!line) return;
      const p = key.split("|");
      line.classList.toggle("edge-hover", !!(name && (p[0] === name || p[1] === name)));
    });
  }

  function setEdgeHover(a, b) {
    graphEls.edges.forEach((grp, key) => {
      const line = lineOf(grp);
      if (!line) return;
      const p = key.split("|");
      const on = !!a && ((p[0] === a && p[1] === b) || (p[0] === b && p[1] === a));
      line.classList.toggle("edge-hover", on);
    });
    graphEls.nodes.forEach((g, k) => {
      g.classList.toggle("hover-nb", !!(a && (k === a || k === b)));
    });
  }

  function focusEdge(a, b) {
    graphEls.edges.forEach((grp) => {
      const line = lineOf(grp);
      if (line) line.classList.remove("focused");
    });
    const key = a < b ? a + "|" + b : b + "|" + a;
    const line = lineOf(graphEls.edges.get(key));
    if (line) line.classList.add("focused");
    $("#related-node").textContent = `${a} ↔ ${b}`;
  }

  function drawMinimap() {
    const cv = $("#graph-minimap");
    if (!cv || cv.classList.contains("hidden") || !Ag.graph.nodes.length) return;
    const ctx = cv.getContext("2d");
    const nodes = Ag.view.nodes;
    const wb = graphEls.bounds || GP.worldBounds(nodes);
    const W = cv.width, H = cv.height;
    const proj = GP.minimapProject(wb, W, H);
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(138,148,166,0.45)";
    const by = {};
    nodes.forEach((n) => (by[n.name] = n));
    Ag.view.edges.forEach((p) => {
      const a = by[p[0]], b = by[p[1]];
      if (!a || !b) return;
      const A = GP.worldToMinimap(proj, a.x, a.y);
      const B = GP.worldToMinimap(proj, b.x, b.y);
      ctx.beginPath();
      ctx.moveTo(A.x, A.y);
      ctx.lineTo(B.x, B.y);
      ctx.stroke();
    });
    nodes.forEach((n) => {
      const P = GP.worldToMinimap(proj, n.x, n.y);
      ctx.beginPath();
      ctx.arc(P.x, P.y, 1.8, 0, 7);
      ctx.fillStyle = FOLDER_COLOR[n.folder] === "var(--folder-root)" ? "#e6edf3" : cssVar(FOLDER_COLOR[n.folder]);
      ctx.fill();
    });
    const vp = GP.viewportRect(
      { scale: GraphView.scale, tx: GraphView.tx, ty: GraphView.ty },
      wb, 760, graphEls.planeH, W, H);
    ctx.strokeStyle = "rgba(232,236,244,0.85)";
    ctx.lineWidth = 1.2;
    ctx.strokeRect(vp.x, vp.y, vp.w, vp.h);
    if (vp.w > 3 && vp.h > 3) {
      ctx.fillStyle = "rgba(232,236,244,0.10)";
      ctx.fillRect(vp.x, vp.y, vp.w, vp.h);
    }
  }

  function scheduleMinimap() {
    if (graphEls.mmRaf) return;
    graphEls.mmRaf = requestAnimationFrame(() => {
      graphEls.mmRaf = null;
      drawMinimap();
    });
  }

  function bindMinimap() {
    const cv = $("#graph-minimap");
    if (!cv) return;
    let dragging = false;
    const navTo = (clientX, clientY) => {
      const wb = graphEls.bounds;
      if (!wb) return;
      const r = cv.getBoundingClientRect();
      const proj = GP.minimapProject(wb, cv.width, cv.height);
      const w = GP.minimapToWorld(proj, clientX - r.left, clientY - r.top);
      GraphView.tx = 760 / 2 - w.x * GraphView.scale;
      GraphView.ty = graphEls.planeH / 2 - w.y * GraphView.scale;
      GraphView.atFit = false;
      applyGraphView();
    };
    cv.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      dragging = true;
      try { cv.setPointerCapture(e.pointerId); } catch (_) { /* no capture */ }
      navTo(e.clientX, e.clientY);
    });
    cv.addEventListener("pointermove", (e) => { if (dragging) navTo(e.clientX, e.clientY); });
    cv.addEventListener("pointerup", () => { dragging = false; });
    cv.addEventListener("pointercancel", () => { dragging = false; });
  }

  function bindGraph() {
    const canvas = $("#graph-svg");
    function endPan() {
      if (!panState.active) return;
      panState.active = false;
      canvas.classList.remove("panning");
      if (panState.pid != null) {
        try { canvas.releasePointerCapture(panState.pid); } catch (_) { /* no capture */ }
      }
    }
    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.button !== 1) return;      // left / middle only
      if (e.target.closest(".g-node") || e.target.closest(".g-edge,.g-hit")) return;
      e.preventDefault();
      canvas.setPointerCapture(e.pointerId);
      panState.active = true;
      panState.pid = e.pointerId;
      panState.px = e.clientX;
      panState.py = e.clientY;
      panState.moved = false;
      canvas.classList.add("panning");
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!panState.active) return;
      const dx = e.clientX - panState.px;
      const dy = e.clientY - panState.py;
      if (GP.didMove(dx, dy)) panState.moved = true;
      const r = _rect();
      GraphView.tx += dx * 760 / Math.max(1, r.width);
      GraphView.ty += dy * graphEls.planeH / Math.max(1, r.height);
      panState.px = e.clientX;
      panState.py = e.clientY;
      GraphView.atFit = false;
      applyGraphView();
    });
    canvas.addEventListener("pointerup", endPan);
    canvas.addEventListener("pointercancel", endPan);
    canvas.addEventListener("click", (e) => {
      if (panState.moved) { panState.moved = false; return; }   // dropped a drag, not a click
      const node = e.target.closest(".g-node");
      if (node) { selectNode(node.dataset.name); return; }
      const edge = e.target.closest(".g-edge,.g-hit");
      if (edge) focusEdge(edge.dataset.a, edge.dataset.b);
    });
    canvas.addEventListener("dblclick", (e) => {
      const node = e.target.closest(".g-node");
      if (node) openNodeModal(node.dataset.name);
    });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const p = planePos(e.clientX, e.clientY);
      zoomBy(Math.pow(1.15, -e.deltaY / 100), p.x, p.y);
    }, { passive: false });
    canvas.addEventListener("pointerover", (e) => {
      const node = e.target.closest(".g-node");
      if (node) { setHover(node.dataset.name); return; }
      const edge = e.target.closest(".g-edge,.g-hit");
      if (edge) setEdgeHover(edge.dataset.a, edge.dataset.b);
    });
    canvas.addEventListener("pointerout", (e) => {
      if (!e.relatedTarget || !canvas.contains(e.relatedTarget)) {
        setHover(null);
        setEdgeHover(null);
      }
    });
    $("#zoom-in").addEventListener("click", () => zoomBy(1.3));
    $("#zoom-out").addEventListener("click", () => zoomBy(1 / 1.3));
    $("#zoom-reset").addEventListener("click", resetGraphView);
    bindMinimap();
    if (window.ResizeObserver && !canvas._ro) {
      canvas._ro = new ResizeObserver(() => reflowGraph());
      canvas._ro.observe(canvas);
    }
    syncViewBox();
  }

  /* ── Phase 24D: graph window resize / detach / fullscreen ─────── */
  const graphWin = { detached: false, fullscreen: false };
  function ssGet(key) { try { return sessionStorage.getItem(key); } catch (_) { return null; } }
  function ssSet(key, val) { try { sessionStorage.setItem(key, val); } catch (_) { /* storage blocked */ } }

  function loadGraphH() {
    const v = parseFloat(ssGet("graph.h"));
    return isFinite(v) && v >= 140 && v <= 560 ? v : 300;
  }

  function loadGraphWindowState() {
    try {
      const raw = ssGet("graph.float");
      const s = raw ? JSON.parse(raw) : null;
      if (s && isFinite(s.w) && isFinite(s.h) && s.w >= 320 && s.h >= 240) return s;
    } catch (_) { /* corrupt state */ }
    return null;
  }

  function saveGraphWindowState() {
    const panel = $("#graph-panel");
    ssSet("graph.float", JSON.stringify({
      x: panel.offsetLeft, y: panel.offsetTop,
      w: panel.offsetWidth, h: panel.offsetHeight,
    }));
  }

  function updateGraphWindowButtons() {
    const detach = $("#graph-detach"), restore = $("#graph-restore");
    const fs = $("#graph-fullscreen");
    if (!detach || !restore || !fs) return;
    const fsOn = !!(document.fullscreenElement || document.webkitFullscreenElement);
    graphWin.fullscreen = fsOn;
    detach.classList.toggle("hidden", graphWin.detached || fsOn);
    restore.classList.toggle("hidden", !graphWin.detached && !fsOn);
    fs.title = fsOn ? "Exit fullscreen" : "Fullscreen";
  }

  function reflowGraph() {
    syncViewBox();
    if (GraphView.atFit) fitGraph(); else applyGraphView();
  }

  function detachGraph() {
    if (graphWin.detached) return;
    const panel = $("#graph-panel"), float = $("#graph-float");
    const saved = loadGraphWindowState();
    const w = saved ? Math.max(320, saved.w) : Math.max(320, Math.round(window.innerWidth * 0.5));
    const h = saved ? Math.max(240, saved.h) : Math.max(240, Math.round(window.innerHeight * 0.55));
    const x = saved ? Math.max(0, Math.min(window.innerWidth - 60, saved.x))
                    : Math.max(24, Math.round((window.innerWidth - w) / 2));
    const y = saved ? Math.max(0, Math.min(window.innerHeight - 40, saved.y))
                    : Math.max(24, Math.round((window.innerHeight - h) / 2));
    panel.style.width = w + "px";
    panel.style.height = h + "px";
    panel.style.left = x + "px";
    panel.style.top = y + "px";
    panel.classList.add("detached");
    $("#graph-fresize").classList.remove("hidden");
    float.classList.remove("hidden");
    float.appendChild(panel);            // moves the same DOM node — graph state survives
    graphWin.detached = true;
    $("#graph-vsplit").classList.add("hidden");
    updateGraphWindowButtons();
    reflowGraph();
  }

  function restoreGraph() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
      return;
    }
    if (graphWin.detached) {
      saveGraphWindowState();
      const panel = $("#graph-panel");
      const vsplit = $("#graph-vsplit");
      vsplit.parentNode.insertBefore(panel, vsplit);   // dock above the splitter
      panel.classList.remove("detached");
      panel.style.left = ""; panel.style.top = "";
      panel.style.width = ""; panel.style.height = "";
      $("#graph-fresize").classList.add("hidden");
      $("#graph-float").classList.add("hidden");
      $("#graph-vsplit").classList.remove("hidden");
      graphWin.detached = false;
    }
    updateGraphWindowButtons();
    reflowGraph();
  }

  function fullscreenGraph() {
    const panel = $("#graph-panel");
    if (document.fullscreenElement) {
      document.exitFullscreen();
      return;
    }
    const req = panel.requestFullscreen || panel.webkitRequestFullscreen;
    if (req) Promise.resolve(req.call(panel)).catch(() => { /* denied */ });
  }

  function bindGraphWindow() {
    $("#graph-detach").addEventListener("click", detachGraph);
    $("#graph-fullscreen").addEventListener("click", fullscreenGraph);
    $("#graph-restore").addEventListener("click", restoreGraph);
    document.addEventListener("fullscreenchange", () => {
      graphWin.fullscreen = !!document.fullscreenElement;
      updateGraphWindowButtons();
      reflowGraph();
    });
    document.addEventListener("webkitfullscreenchange", () => {
      graphWin.fullscreen = !!document.webkitFullscreenElement;
      updateGraphWindowButtons();
      reflowGraph();
    });

    // docked panel height splitter (graph panel ↔ related files)
    const gv = $("#graph-vsplit");
    gv.addEventListener("mousedown", (e) => {
      e.preventDefault();
      gv.classList.add("dragging");
      const startY = e.clientY;
      const startH = parseFloat(getComputedStyle(document.body).getPropertyValue("--graph-h")) || 300;
      const move = (ev) => {
        const h = Math.min(560, Math.max(140, startH + (ev.clientY - startY)));
        document.body.style.setProperty("--graph-h", h + "px");
      };
      const up = () => {
        gv.classList.remove("dragging");
        const gh = parseFloat(getComputedStyle(document.body).getPropertyValue("--graph-h"));
        ssSet("graph.h", String(gh));
        post("/api/prefs", { graph_h: gh }).catch(() => {});
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });

    // detached window: drag via the title bar, resize via the corner handle
    const panel = $("#graph-panel");
    panel.querySelector(".panel-title").addEventListener("pointerdown", (e) => {
      if (!graphWin.detached || document.fullscreenElement || e.target.closest("button")) return;
      e.preventDefault();
      const startX = e.clientX, startY = e.clientY;
      const ox = panel.offsetLeft, oy = panel.offsetTop;
      const move = (ev) => {
        panel.style.left = Math.max(0, Math.min(window.innerWidth - 60, ox + (ev.clientX - startX))) + "px";
        panel.style.top = Math.max(0, Math.min(window.innerHeight - 40, oy + (ev.clientY - startY))) + "px";
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        saveGraphWindowState();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
    $("#graph-fresize").addEventListener("pointerdown", (e) => {
      if (!graphWin.detached) return;
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX, startY = e.clientY;
      const sw = panel.offsetWidth, sh = panel.offsetHeight;
      const move = (ev) => {
        panel.style.width = Math.max(320, Math.min(window.innerWidth - panel.offsetLeft, sw + (ev.clientX - startX))) + "px";
        panel.style.height = Math.max(240, Math.min(window.innerHeight - panel.offsetTop, sh + (ev.clientY - startY))) + "px";
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        saveGraphWindowState();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
    updateGraphWindowButtons();
  }

  async function selectNode(name) {
    Ag.selectedNode = name;
    Ag.prefs.selected_node = name;
    applyGraphSelection();
    $("#node-open").disabled = false;
    $("#send-ctx").disabled = false;
    $("#related-node").textContent = name;
    await renderRelated(name);
  }

  /* ─────────────────────── related files ─────────────────────── */
  async function renderRelated(name) {
    const nav = $("#related-nav");
    empty(nav);
    if (!name) return;
    let rel;
    try {
      rel = await api(`/api/vault/node/${encodeURIComponent(name)}/related`);
    } catch (err) {
      nav.appendChild(el("div", "placeholder", String(err.message || err)));
      return;
    }
    const group = (title, items, selected) => {
      const wrap = el("div", "rel-group");
      if (!items.length) return wrap;
      wrap.appendChild(el("div", "rel-group-hd", `${title} (${items.length})`));
      items.forEach((it) => {
        const row = el("div", "rel-item" + (it.name === selected ? " selected" : ""));
        const nameRow = el("div", "rel-name", it.name);
        row.appendChild(nameRow);
        const meta = el("div", "rel-meta");
        meta.appendChild(el("span", "rel-type", it.folder + " · " + it.type));
        row.appendChild(meta);
        row.appendChild(el("div", "rel-snip", (it.snippet || "").slice(0, 100)));
        row.addEventListener("click", () => selectNode(it.name));
        wrap.appendChild(row);
      });
      return wrap;
    };
    nav.appendChild(group("Links", rel.links, name));
    nav.appendChild(group("Backlinks", rel.backlinks, name));
  }

  function buildContextPrompt(pkg) {
    const lines = [];
    lines.push(`Vault context resolved for [[${pkg.root}]] (control-plane graph node).`);
    lines.push("");
    pkg.nodes.slice(0, 8).forEach((ref) => {
      lines.push(`# ${ref.name}  [${ref.type} · depth ${ref.depth}]`);
      const snip = (ref.snippet || "").replace(/\n{3,}/g, "\n\n");
      lines.push(snip.slice(0, 500));
      lines.push("");
    });
    if (!pkg.nodes.length) lines.push("(no linked context resolved)");
    lines.push("");
    lines.push("Use the above vault context to continue the work. Report what you changed.");
    return lines.join("\n");
  }

  function bindSendContext() {
    $("#send-ctx").addEventListener("click", async () => {
      const node = Ag.selectedNode;
      const tag = Ag.activeTag;
      if (!node || !tag) return;
      try {
        const pkg = await api(`/api/vault/context/${encodeURIComponent(node)}`);
        await post("/api/dispatch", { prompt: buildContextPrompt(pkg), agent: tag });
      } catch (err) {
        console.error(err);
      }
    });
  }

  /* ─────────────────────── node modal ────────────────────────── */
  async function openNodeModal(name) {
    const data = await api(`/api/vault/node/${encodeURIComponent(name)}`);
    $("#modal-title").textContent = name;
    const body = $("#modal-body");
    empty(body);
    if (data.frontmatter_error) body.appendChild(el("div", "muted", "⚠ " + data.frontmatter_error));
    const fm = el("div", "task-fm");
    Object.entries(data.fields).forEach(([k, v]) => {
      fm.appendChild(el("div", "k", k));
      fm.appendChild(el("div", null, String(v)));
    });
    body.appendChild(fm);
    const pre = el("pre", null, data.body);
    body.appendChild(pre);
    $("#modal-backdrop").classList.remove("hidden");
  }

  function bindModal() {
    $("#modal-close").addEventListener("click", () => $("#modal-backdrop").classList.add("hidden"));
    $("#modal-backdrop").addEventListener("click", (e) => {
      if (e.target === $("#modal-backdrop")) $("#modal-backdrop").classList.add("hidden");
    });
  }

  /* ─────────────────────── tasks tab ─────────────────────────── */
  async function loadTasks() {
    try { Ag.tasks = (await api("/api/tasks")).tasks; } catch (err) { Ag.tasks = []; }
    renderTaskList();
    if (Ag.taskDetail) refreshTaskDetail(Ag.taskDetail.name);
  }

  function renderTaskList() {
    const list = $("#task-list");
    empty(list);
    Ag.tasks.forEach((t) => {
      const li = el("li", "task-item" + (Ag.taskDetail && Ag.taskDetail.name === t.name ? " selected" : ""));
      li.appendChild(el("div", "t-name", t.name));
      li.appendChild(el("div", "t-meta",
        `${t.status} · ${t.priority || "-"} · ${(t.assigned_agent || "unassigned").replace("Agent_", "")}`));
      li.addEventListener("click", () => selectTask(t.name));
      list.appendChild(li);
    });
  }

  async function selectTask(name) {
    Ag.taskDetail = { name };
    renderTaskList();
    await refreshTaskDetail(name);
  }

  async function refreshTaskDetail(name) {
    const wrap = $("#task-detail-body");
    empty(wrap);
    let data;
    try {
      data = await api(`/api/vault/node/${encodeURIComponent(name)}`);
    } catch (err) {
      wrap.appendChild(el("div", "placeholder", String(err.message || err)));
      return;
    }
    Ag.taskDetail = Object.assign({}, Ag.taskDetail, data);
    const fm = el("div", "task-fm");
    [["status", data.fields.status], ["priority", data.fields.priority],
     ["assigned_agent", data.fields.assigned_agent], ["type", data.fields.type],
     ["updated", data.fields.updated]].forEach(([k, v]) => {
      fm.appendChild(el("div", "k", k));
      fm.appendChild(el("div", null, v || "—"));
    });
    wrap.appendChild(fm);

    const actions = el("div", "task-actions");
    const agentSel = el("select");
    Ag.agents.forEach((a) => {
      if (!a.agent) return;
      const opt = el("option", null, `${a.tag.toUpperCase()} · ${a.name}`);
      opt.value = a.agent;
      if (("Agent_" + a.name) === data.fields.assigned_agent) opt.selected = true;
      agentSel.appendChild(opt);
    });
    const assignBtn = el("button", "btn primary", "Assign");
    const statusSel = el("select");
    TASK_STATUSES.forEach((s) => {
      const opt = el("option", null, s);
      opt.value = s;
      if (s === data.fields.status) opt.selected = true;
      statusSel.appendChild(opt);
    });
    const statusBtn = el("button", "btn", "Set status");
    const runBtn = el("button", "btn danger", "Run (dispatch)");
    const msg = el("span", "task-msg", "");
    actions.appendChild(el("label", null, "assign:"));
    actions.appendChild(agentSel);
    actions.appendChild(assignBtn);
    actions.appendChild(el("label", null, "status:"));
    actions.appendChild(statusSel);
    actions.appendChild(statusBtn);
    actions.appendChild(runBtn);
    actions.appendChild(msg);

    // Task-level role override — temporary, never mutates roles.json.
    const roleSel = el("select");
    const noneOpt = el("option", null, "(default roles)");
    noneOpt.value = "";
    roleSel.appendChild(noneOpt);
    try {
      const r = await api("/api/settings/roles");
      (r.roles || []).forEach((role) => {
        const opt = el("option", null, role.name || role.id);
        opt.value = role.id;
        roleSel.appendChild(opt);
      });
    } catch (_) { /* roles unavailable; clearing still works */ }
    roleSel.value = data.fields.role || "";
    const roleBtn = el("button", "btn", "Set role override");
    actions.appendChild(el("label", null, "role override:"));
    actions.appendChild(roleSel);
    actions.appendChild(roleBtn);
    wrap.appendChild(actions);

    assignBtn.addEventListener("click", async () => {
      try {
        const res = await post(`/api/tasks/${encodeURIComponent(name)}/assign`, { agent: agentSel.value });
        msg.textContent = `assigned → ${res.assigned_agent} (${res.status})`;
        msg.style.color = "var(--ok)";
        loadTasks();
      } catch (err) {
        msg.textContent = err.message;
        msg.style.color = "var(--err)";
      }
    });
    statusBtn.addEventListener("click", async () => {
      try {
        const res = await post(`/api/tasks/${encodeURIComponent(name)}/status`, { status: statusSel.value });
        msg.textContent = `status → ${res.status}`;
        msg.style.color = "var(--ok)";
        loadTasks();
      } catch (err) {
        msg.textContent = err.message;
        msg.style.color = "var(--err)";
      }
    });
    roleBtn.addEventListener("click", async () => {
      try {
        const res = await api(`/api/tasks/${encodeURIComponent(name)}/role`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: roleSel.value || null }),
        });
        msg.textContent = res.role
          ? `role override → ${res.role}`
          : "role override cleared (agent's assigned roles apply)";
        msg.style.color = "var(--ok)";
      } catch (err) {
        msg.textContent = err.message;
        msg.style.color = "var(--err)";
      }
    });
    runBtn.addEventListener("click", async () => {
      try {
        const res = await post(`/api/tasks/${encodeURIComponent(name)}/dispatch`);
        msg.textContent = `dispatch started (running: ${res.running})`;
        msg.style.color = "var(--ok)";
        switchTab("execution");
      } catch (err) {
        msg.textContent = err.message;
        msg.style.color = "var(--err)";
      }
    });

    const bodyEl = el("div", "task-body", data.body);
    wrap.appendChild(bodyEl);
  }

  /* ─────────────────────── logs tab ──────────────────────────── */
  function buildLogSelect() {
    const sel = $("#log-select");
    empty(sel);
    const opt = el("option", null, "orchestrator.log");
    opt.value = "orchestrator";
    sel.appendChild(opt);
    Ag.agents.forEach((a) => {
      const o = el("option", null, `${a.tag}.log`);
      o.value = a.tag;
      sel.appendChild(o);
    });
    sel.addEventListener("change", () => { Ag.logKey = sel.value; loadLog(); });
    $("#logs-refresh").addEventListener("click", loadLog);
  }

  async function loadLog() {
    const out = $("#log-output");
    empty(out);
    out.textContent = "(loading…)";
    let key = Ag.logKey;
    try {
      const data = key === "orchestrator"
        ? await api("/api/logs/orchestrator")
        : await api(`/api/logs/${encodeURIComponent(key)}`);
      out.textContent = data.lines.join("\n") || "(empty log)";
    } catch (err) {
      out.textContent = err.message;
    }
  }

  /* ─────────────────────── tabs / modal / splitters ──────────── */
  function bindTabs() {
    $$(".tab").forEach((tab) => {
      tab.addEventListener("click", () => switchTab(tab.dataset.tab));
    });
  }

  function switchTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
    if (name === "logs") loadLog();
    if (name === "tasks") loadTasks();
  }

  /* ── Bottom Status/Tasks/Execution/Logs dock (minimize → compact bar) ── */
  function setBottomMinimized(min) {
    Ag.bottomMinimized = !!min;
    const body = document.body;
    const btn = $("#bottom-toggle");
    if (min) {
      Ag.bottomExpandedH =
        parseFloat(getComputedStyle(body).getPropertyValue("--bottom-h"))
        || Ag.bottomExpandedH || 200;
      body.classList.add("bottom-minimized");
      body.style.setProperty("--bottom-h", BOTTOM_MIN_H + "px");
    } else {
      body.classList.remove("bottom-minimized");
      body.style.setProperty("--bottom-h", (Ag.bottomExpandedH || 200) + "px");
    }
    if (btn) {
      btn.textContent = min ? "▔" : "▁";
      btn.title = min ? "Expand the bottom dock" : "Minimize the bottom dock";
    }
    try { localStorage.setItem(BOTTOM_MIN_KEY, min ? "1" : "0"); } catch (_) { /* blocked */ }
    if (!min) { try { localStorage.setItem(BOTTOM_H_KEY, String(Ag.bottomExpandedH || 200)); } catch (_) {} }
    // Reflow agent windows into the new available vertical space.
    buildWorkspace();
  }
  function toggleBottomDock() { setBottomMinimized(!Ag.bottomMinimized); }

  function loadBottomDockState() {
    let min = false;
    try { min = localStorage.getItem(BOTTOM_MIN_KEY) === "1"; } catch (_) { /* blocked */ }
    if (!min) return;
    Ag.bottomMinimized = true;
    try {
      const h = parseFloat(localStorage.getItem(BOTTOM_H_KEY));
      if (Number.isFinite(h)) Ag.bottomExpandedH = h;
    } catch (_) { /* blocked */ }
    document.body.classList.add("bottom-minimized");
    document.body.style.setProperty("--bottom-h", BOTTOM_MIN_H + "px");
    const btn = $("#bottom-toggle");
    if (btn) { btn.textContent = "▔"; btn.title = "Expand the bottom dock"; }
  }

  function bindSplitters() {
    const v = $("#vsplit"), h = $("#hsplit");
    const setWinPref = () => {
      const pref = { sidebar_w: parseFloat(getComputedStyle(document.body).getPropertyValue("--sidebar-w")),
                     bottom_h: parseFloat(getComputedStyle(document.body).getPropertyValue("--bottom-h")) };
      post("/api/prefs", pref).catch(() => {});
    };
    v.addEventListener("mousedown", (e) => {
      e.preventDefault();
      v.classList.add("dragging");
      const move = (ev) => {
        const w = Math.min(560, Math.max(160, ev.clientX));
        document.body.style.setProperty("--sidebar-w", w + "px");
      };
      const up = () => {
        v.classList.remove("dragging");
        setWinPref();
        buildWorkspace();  // reflow panels to the new workspace width
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
    h.addEventListener("mousedown", (e) => {
      e.preventDefault();
      h.classList.add("dragging");
      const move = (ev) => {
        const bh = Math.min(560, Math.max(120, window.innerHeight - ev.clientY));
        document.body.style.setProperty("--bottom-h", bh + "px");
      };
      const up = () => {
        h.classList.remove("dragging");
        setWinPref();
        buildWorkspace();  // reflow panels to the new workspace height
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
  }

  function applyPrefs() {
    if (Ag.prefs.sidebar_w) document.body.style.setProperty("--sidebar-w", Ag.prefs.sidebar_w + "px");
    if (Ag.prefs.bottom_h) document.body.style.setProperty("--bottom-h", Ag.prefs.bottom_h + "px");
    if (Ag.prefs.graph_h) document.body.style.setProperty("--graph-h", Ag.prefs.graph_h + "px");
    const segActive = Ag.prefs.layout;
    $$(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.layout === segActive));
    Ag.activeTag = Ag.prefs.active_tag;
  }

  function savePrefs() {
    Ag.prefs.active_tag = Ag.activeTag;
    Ag.prefs.selected_node = Ag.selectedNode;
    post("/api/prefs", {
      layout: Ag.prefs.layout,
      agents_visible: Ag.prefs.agents_visible,
      active_tag: Ag.prefs.active_tag,
      selected_node: Ag.prefs.selected_node,
    }).catch(() => {});
  }

  /* ─────────────────────── SSE stream ────────────────────────── */
  function appendMaster(ev) {
    if (!["run", "line", "status", "error"].includes(ev.kind)) return;
    appendEv($("#master-console"), ev);
  }

  let _stream = null;
  function openStream() {
    // Idempotent: a BFCache restore (or re-init) must not stack duplicate
    // EventSource connections that would double-render output.
    if (_stream) { try { _stream.close(); } catch (_) { /* already closed */ } _stream = null; }
    const es = new EventSource("/api/events/stream");
    _stream = es;
    const kinds = ["run", "line", "error", "status", "taskline", "usermsg"];
    kinds.forEach((kind) => {
      es.addEventListener(kind, (event) => {
        let ev;
        try { ev = JSON.parse(event.data); } catch (_) { return; }
        const tag = ev.tag;
        const isAgent = Ag.agents.some((a) => a.tag === tag);
        if (isAgent) {
          onAgentEvent(tag, ev);
          if (ev.kind === "status") syncStatusRow(tag, ev.text);
        } else if (kind === "taskline") {
          appendEv($("#execution-console"), { kind: "taskline", text: ev.text });
        } else {
          appendMaster(ev);
        }
      });
    });
    es.onerror = () => { /* EventSource reconnects by itself */ };
  }

  /* ─────────────────────── periodic sync ─────────────────────── */
  // Watermark of the backend WebState event sequence ("n" in /api/state and in
  // every SSE event). Within one server process it only ever grows; if it drops,
  // the backend restarted and its per-agent event sequence restarted with it.
  // Without this check, the stale in-memory sessions would make onAgentEvent's
  // n-dedup swallow the new process's events as "already seen" — the agent runs
  // and its status updates, but no output rows ever render.
  let lastBackendN = 0;

  // Returns whether a restart was detected (used by the headless test hook);
  // pollState ignores the return value.
  function checkBackendRestart(snapN) {
    if (snapN === undefined) return false;
    if (snapN < lastBackendN) {
      // backend restarted — its own _sessions were reset too, so drop the mirror
      Ag.sessions = {};
      lastBackendN = snapN;
      buildWorkspace();
      return true;
    }
    lastBackendN = snapN;
    return false;
  }

  async function pollState() {
    try {
      const snap = await api("/api/state");
      // Restart detection runs on the 3s poll cadence, so output that arrives
      // within the first ~3s after a restart is the only theoretical window;
      // real opencode output lands seconds later, always after the clear.
      checkBackendRestart(snap.n);
      Ag.agents.forEach((a) => {
        const st = snap.statuses[a.tag]; const prog = snap.progress[a.tag];
        const toks = snap.token_usage[a.tag]; const running = snap.session_tags.includes(a.tag);
        if (a.status !== st) { a.status = st; }
        if (a.progress !== prog) a.progress = prog;
        if (a.token_usage !== toks) a.token_usage = toks;
        if (a.running !== running) a.running = running;
      });
      // refresh panels + status rows only if external changes occurred
      $$(".panel").forEach((card) => {
        const a = Ag.agents.find((x) => x.tag === card.dataset.tag);
        if (a) updatePanelUi(card, a);
      });
      buildStatusTable();
      // reconcile Home with the active workflow graph (activate/switch/save)
      // and stream the active workflow run into node-aware consoles
      await refreshActiveWorkflow();
      await pollActiveRun();
    } catch (_) { /* transient */ }
  }

  /* ─────────────────────── loaders ───────────────────────────── */
  async function loadAgents() {
    const data = await api("/api/agents");
    Ag.agents = data.agents;
    Ag.prefs = Object.assign({}, Ag.prefs, data.prefs || {});
    Ag.activeTag = Ag.prefs.active_tag;
    await refreshActiveWorkflow();
    applyPrefs();
    loadBottomDockState();
    buildPop();
    buildDispatchTarget();
    buildStatusTable();
    buildWorkspace();
    buildLogSelect();
    $("#send-target").textContent = tagName(Ag.activeTag);
    $("#workspace-dir").textContent = window.location.host;
  }

  function homeSignatureOf(wf) {
    if (!wf) return "";
    return JSON.stringify([
      wf.id,
      (wf.nodes || []).map((n) =>
        [n.id, n.agent, n.model, n.x, n.y, n.enabled, n.kind, n.label]),
      (wf.edges || []).map((e) => [e.source, e.target, e.condition]),
    ]);
  }

  async function refreshActiveWorkflow() {
    // The Workflow Designer's saved graph (if activated) is the single source
    // of truth for Home agent windows. This is idempotent: it re-fetches on
    // every poll and reconciles Home ONLY when the graph actually changed
    // (activate/switch/rename/move/model/edge edits in the Designer flow
    // through here automatically — no stale legacy windows survive).
    let data = null;
    try { data = await api("/api/active-workflow"); } catch (_) { return; }
    const wf = data && data.workflow;
    const sig = homeSignatureOf(wf);
    if (sig === Ag.homeSignature) return;
    Ag.homeSignature = sig;
    if (wf) {
      // An active workflow is projected even when it has zero agent nodes;
      // only ``workflow: null`` (no active id / missing file) is "inactive".
      Ag.homeWorkflow = wf;
      Ag.homeNodes = (wf.nodes || []).filter((n) => n.kind === "agent");
      Ag.homeEdges = wf.edges || [];
    } else {
      Ag.homeWorkflow = null; Ag.homeNodes = []; Ag.homeEdges = [];
    }
    buildWorkspace();
    buildDispatchTarget();
  }

  async function refreshAgentModels() {
    // Re-read /api/agents and sync model labels into Ag.agents + panel headers.
    try {
      const data = await api("/api/agents");
      const byTag = new Map(data.agents.map((x) => [x.tag, x]));
      Ag.agents.forEach((a) => {
        const fresh = byTag.get(a.tag);
        if (fresh) a.model = fresh.model;
      });
      buildPop();
      buildDispatchTarget();
      $$(".panel").forEach((card) => {
        const a = Ag.agents.find((x) => x.tag === card.dataset.tag);
        if (a) updatePanelUi(card, a);
      });
    } catch (_) { /* transient */ }
  }

  async function loadSessions() {
    try {
      const data = await api("/api/sessions");
      const incoming = data.sessions || {};
      // Merge, never replace: live SSE events that already arrived (and the
      // snapshot events not yet delivered live) must not be reverted by the
      // init snapshot. The snapshot is a prefix of the SSE timeline, so n-dedup
      // keeps per-tag order intact while preserving all received output.
      for (const tag of Object.keys(incoming)) {
        const cur = Ag.sessions[tag] || [];
        const have = new Set(cur.filter((e) => e.n !== undefined).map((e) => e.n));
        const merged = cur.slice();
        for (const e of incoming[tag]) {
          if (e.n !== undefined && have.has(e.n)) continue;
          merged.push(e);
          if (e.n !== undefined) have.add(e.n);
        }
        if (merged.length > SESSION_TAIL) merged.splice(0, merged.length - SESSION_TAIL);
        Ag.sessions[tag] = merged;
      }
      // rebuild any panels to replay history (current sessions, not a snapshot)
      buildWorkspace();
      // watermark the backend event sequence so pollState can detect a backend
      // restart (WebState "n" resets to 0) even if it happens before the first poll.
      for (const tag of Object.keys(incoming)) {
        for (const e of incoming[tag]) {
          if (e.n !== undefined && e.n > lastBackendN) lastBackendN = e.n;
        }
      }
    } catch (_) { /* ignore */ }
  }

  async function loadGraph(refresh) {
    const data = await api("/api/vault/graph" + (refresh ? "?refresh=true" : ""));
    Ag.graph = data;
    graphEls = { svg: null, world: null, nodes: new Map(), edges: new Map(),
                 byName: {}, sectionHubs: {} };
    GraphView.scale = 1; GraphView.tx = 0; GraphView.ty = 0;
    Ag.selectedNode = Ag.prefs.selected_node;
    Ag.sectionFilter = [];   // a refresh starts from the full graph again
    Ag.coreView = false;
    refreshGraphView();
    if (Ag.selectedNode) {
      await renderRelated(Ag.selectedNode);
    } else {
      renderRelated(null);
    }
  }

  /* ─────────────────────── init ──────────────────────────────── */
  function init() {
    loadHomeLayouts();
    bindLayout();
    bindHomeLayout();
    bindAgentsPop();
    bindDispatch();
    bindGraph();
    bindSendContext();
    bindModal();
    bindTabs();
    bindSplitters();
    bindGraphWindow();
    const bottomToggle = $("#bottom-toggle");
    if (bottomToggle) bottomToggle.addEventListener("click", toggleBottomDock);
    document.body.style.setProperty("--graph-h", loadGraphH() + "px");
    const settingsBtn = $("#settings-btn");
    if (settingsBtn && window.MACSettings) {
      settingsBtn.addEventListener("click", () => window.MACSettings.open());
    }
    loadAgents().catch((err) => console.error(err));
    loadSessions();
    loadGraph();
    loadTasks();
    openStream();
    setInterval(pollState, 3000);
    // BFCache restore (navigating Home → Workflow → back) kills the SSE
    // connection and can leave the workspace stale; re-open the stream and
    // reconcile on restore / visibility so agent windows reappear without a
    // manual reload.
    window.addEventListener("pageshow", (e) => {
      if (e.persisted) {
        openStream();
        refreshActiveWorkflow();
        loadSessions();
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        openStream();
        refreshActiveWorkflow();
      }
    });
  }

  window.addEventListener("DOMContentLoaded", init);

  // Test/embedding hook (mirrors window.MACSettings): exposes the live event →
  // session pipeline so behavioral tests can drive it headlessly.
  window.MACApp = { Ag, onAgentEvent, buildWorkspace, panelEl, appendEv, openStream,
                    loadSessions, checkBackendRestart, pollState, refreshAgentModels,
                    refreshActiveWorkflow, buildWorkflowWorkspace, nodeEvent,
                    pollActiveRun, setActiveNode, homeSignatureOf,
                    setHomeLayout, setHomeZoom, resetHomeLayout, setCustomNode,
                    moveNode, resizeNode, resizeNodeDelta, redrawHomeEdges,
                    computeLayout, currentHomeLayout, workflowOrder, buildWorkspace,
                    switchToCustom, clampToWorkspace, bindPanelInteractions,
                    bringToFront, commitCustomLayout,
                    toggleBottomDock, setBottomMinimized, loadBottomDockState,
                    dispatchTargetNodes, renderUserMessage, markNodesWorking,
                    setPanelRunStatus, RESIZE_DIRS, RESIZE_EDGES, avatarColor,
                    layoutGraph };
})();
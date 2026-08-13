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
    Ag.agents.forEach((a) => {
      const opt = el("option", null, `${a.tag.toUpperCase()} · ${a.name}`);
      opt.value = a.tag;
      sel.appendChild(opt);
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
      let tag = $("#prompt-target").value;
      if (tag === "active") tag = Ag.activeTag;
      if (tag === "all") tag = null;
      if (tag && !Ag.agents.some((a) => a.tag === tag)) tag = null;
      try {
        await post("/api/dispatch", { prompt, agent: tag });
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
  function visibleAgents() {
    const visible = Ag.prefs.agents_visible || [];
    const agents = [];
    for (const a of Ag.agents) {           // AGENTS roster order preserved
      if (visible.includes(a.tag)) agents.push(a);
    }
    const count = Math.min(parseInt(Ag.prefs.layout, 10) || 4, agents.length);
    return agents.slice(0, count);
  }

  function gridFor(count) {
    const base = "minmax(180px, 1fr)";
    if (count <= 1) return { cols: "1fr", rows: "1fr" };
    if (count === 2) return { cols: "1fr 1fr", rows: `${base}` };
    if (count === 3) return { cols: "1fr 1fr 1fr", rows: `${base}` };
    if (count === 4) return { cols: "1fr 1fr", rows: `${base} ${base}` };
    return { cols: "1fr 1fr 1fr", rows: `${base} ${base}` }; // 5–6
  }

  function statusCls(status) {
    if (status === "active") return "st-ok";
    if (status === "error") return "st-err";
    if (status === "thinking") return "st-busy";
    return "st-idle";
  }

  function panelFor(a) {
    const card = el("section", "panel");
    card.dataset.tag = a.tag;
    const head = el("header", "p-head");
    head.appendChild(el("span", "p-name", `${a.tag.toUpperCase()} · ${a.name}`));
    head.appendChild(el("span", "p-model", a.model || ""));
    const status = el("span", "p-status st-idle");
    status.appendChild(el("span", "dot"));
    status.appendChild(el("span", "p-status-label", "idle"));
    head.appendChild(status);
    const stop = el("button", "p-stop", "Stop");
    stop.disabled = !a.running;
    stop.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      try { await post(`/api/stop/${a.tag}`); } catch (err) { console.error(err); }
    });
    head.appendChild(stop);
    card.appendChild(head);

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
    card.addEventListener("click", () => setActive(a.tag));

    updatePanelUi(card, a);
    return card;
  }

  function updatePanelUi(card, a) {
    const label = card.querySelector(".p-status-label");
    label.textContent = STATUS_LABEL[a.status] || a.status;
    card.querySelector(".p-status").className = "p-status " + statusCls(a.status);
    card.querySelector(".p-stop").disabled = !a.running;
    card.querySelector(".p-task").textContent = a.prompt || "…";
    card.querySelector(".p-task").title = a.prompt || "";
    card.querySelector(".fill").style.width = (a.progress || 0) + "%";
    const modelEl = card.querySelector(".p-model");
    if (modelEl) modelEl.textContent = a.model || "";
    card.classList.toggle("active", a.tag === Ag.activeTag);
  }

  function buildWorkspace() {
    const wg = $("#workspace-grid");
    empty(wg);
    const agents = visibleAgents();
    const emptyMsg = el("div", "workspace-empty hidden", "No agents visible — toggle agents on in the toolbar.");
    wg.appendChild(emptyMsg);
    if (agents.length === 0) {
      emptyMsg.classList.remove("hidden");
    }
    const g = gridFor(agents.length);
    wg.style.gridTemplateColumns = g.cols;
    wg.style.gridTemplateRows = g.rows;
    agents.forEach((a) => wg.appendChild(panelFor(a)));
    // replay saved sessions (current Ag.sessions, not an init snapshot; status
    // events are skipped so live and replay rendering stay identical)
    for (const a of Ag.agents) {
      const card = wg.querySelector(`.panel[data-tag="${a.tag}"]`);
      if (card && Ag.sessions[a.tag]) {
        Ag.sessions[a.tag].forEach((ev) => {
          if (PANEL_KINDS.includes(ev.kind)) {
            appendEv(card.querySelector(".p-console"), ev);
          }
        });
      }
    }
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
    const sig = nodes.map((nd) => nd.name).join("|") + "::" +
                edges.map((p) => p.join("-")).join("|");
    if (graphEls.layoutSig === sig && graphEls.cachedPos.length === nodes.length) {
      const map = {};
      nodes.forEach((nd, i) => (map[nd.name] = graphEls.cachedPos[i]));
      nodes.forEach((nd) => {
        const p = map[nd.name];
        if (p) { nd.x = p.x; nd.y = p.y; }
      });
      return;
    }
    GP.runLayout(nodes, edges, { iterations: 500 });
    graphEls.cachedPos = nodes.map((nd) => ({ x: nd.x, y: nd.y }));
    graphEls.layoutSig = sig;
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

  function openStream() {
    const es = new EventSource("/api/events/stream");
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
    } catch (_) { /* transient */ }
  }

  /* ─────────────────────── loaders ───────────────────────────── */
  async function loadAgents() {
    const data = await api("/api/agents");
    Ag.agents = data.agents;
    Ag.prefs = Object.assign({}, Ag.prefs, data.prefs || {});
    Ag.activeTag = Ag.prefs.active_tag;
    applyPrefs();
    buildPop();
    buildDispatchTarget();
    buildStatusTable();
    buildWorkspace();
    buildLogSelect();
    $("#send-target").textContent = tagName(Ag.activeTag);
    $("#workspace-dir").textContent = window.location.host;
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
    bindLayout();
    bindAgentsPop();
    bindDispatch();
    bindGraph();
    bindSendContext();
    bindModal();
    bindTabs();
    bindSplitters();
    bindGraphWindow();
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
  }

  window.addEventListener("DOMContentLoaded", init);

  // Test/embedding hook (mirrors window.MACSettings): exposes the live event →
  // session pipeline so behavioral tests can drive it headlessly.
  window.MACApp = { Ag, onAgentEvent, buildWorkspace, panelEl, appendEv, openStream, loadSessions, checkBackendRestart, pollState, refreshAgentModels };
})();
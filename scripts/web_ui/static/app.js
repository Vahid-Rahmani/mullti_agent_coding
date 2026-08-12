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

  /* ─────────────────────────── state ─────────────────────────── */
  const Ag = {
    agents: [],                 // roster from /api/agents
    sessions: {},               // tag -> [{kind,text,n}]
    prefs: { layout: "4", agents_visible: [], active_tag: null, selected_node: null },
    graph: { nodes: [], edges: [] },
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
    const sel = $("#dispatch-target");
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
    $("#dispatch-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = $("#dispatch-input");
      const prompt = input.value.trim();
      if (!prompt) return;
      let tag = $("#dispatch-target").value;
      if (tag === "active") tag = Ag.activeTag;
      if (tag === "all") tag = null;
      if (tag && !Ag.agents.some((a) => a.tag === tag)) tag = null;
      try {
        await post("/api/dispatch", { prompt, agent: tag });
        input.value = "";
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
    card.classList.toggle("active", a.tag === Ag.activeTag);
  }

  function buildWorkspace() {
    const ws = $("#workspace");
    empty(ws);
    const agents = visibleAgents();
    const emptyMsg = el("div", "workspace-empty hidden", "No agents visible — toggle agents on in the toolbar.");
    ws.appendChild(emptyMsg);
    if (agents.length === 0) {
      emptyMsg.classList.remove("hidden");
    }
    const g = gridFor(agents.length);
    ws.style.gridTemplateColumns = g.cols;
    ws.style.gridTemplateRows = g.rows;
    agents.forEach((a) => ws.appendChild(panelFor(a)));
    // replay saved sessions
    for (const a of Ag.agents) {
      const card = ws.querySelector(`.panel[data-tag="${a.tag}"]`);
      if (card && Ag.sessions[a.tag]) {
        Ag.sessions[a.tag].forEach((ev) => appendEv(card.querySelector(".p-console"), ev));
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
    // live telemetry sync for a specific agent
    const card = panelEl(tag);
    if (card) {
      if (ev.kind === "status") {
        const label = card.querySelector(".p-status-label");
        if (label) label.textContent = STATUS_LABEL[ev.text] || ev.text;
        card.querySelector(".p-status").className = "p-status " + statusCls(ev.text);
      }
      if (ev.kind === "run") {
        card.querySelector(".p-task").textContent = ev.text.split("::")[1] || ev.text;
        card.querySelector(".p-task").title = ev.text;
      }
      if (["run", "line", "error", "usermsg", "taskline"].includes(ev.kind)) {
        appendEv(card.querySelector(".p-console"), ev);
      }
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

  /* ─────────────────────── graph view ────────────────────────── */
  let graphEls = { svg: null, nodes: new Map(), edges: new Map() };

  function layoutGraph(nodes, edges) {
    const W = 760, H = 440;
    const n = nodes.length;
    const pos = nodes.map((nd, i) => {
      const ang = (i / Math.max(1, n)) * Math.PI * 2;
      const r = 70 + (i % 6) * 20;
      return { x: W / 2 + Math.cos(ang) * r, y: H / 2 + Math.sin(ang) * r };
    });
    const k = Math.sqrt((W * H) / Math.max(1, n)) * 0.55;
    const idx = {};
    nodes.forEach((nd, i) => (idx[nd.name] = i));
    const e = edges
      .filter((p) => idx[p[0]] != null && idx[p[1]] != null)
      .map((p) => [idx[p[0]], idx[p[1]]]);

    let t = 9;
    for (let it = 0; it < 220; it++) {
      const f = nodes.map(() => ({ x: 0, y: 0 }));
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
        let d2 = dx * dx + dy * dy; if (d2 < 1) d2 = 1;
        const d = Math.sqrt(d2); dx /= d; dy /= d;
        const force = (k * k) / d2;
        f[i].x += dx * force; f[i].y += dy * force;
        f[j].x -= dx * force; f[j].y -= dy * force;
      }
      for (const [a, b] of e) {
        const dx = pos[b].x - pos[a].x, dy = pos[b].y - pos[a].y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (d * d) / k;                       // tension (damped)
        const ux = dx / d, uy = dy / d;
        f[a].x += ux * force; f[a].y += uy * force;
        f[b].x -= ux * force; f[b].y -= uy * force;
      }
      for (let i = 0; i < n; i++) {
        f[i].x += (W / 2 - pos[i].x) * 0.012;
        f[i].y += (H / 2 - pos[i].y) * 0.012;
      }
      for (let i = 0; i < n; i++) {
        const fl = Math.sqrt(f[i].x ** 2 + f[i].y ** 2) || 1;
        const scale = Math.min(fl, t) / fl;
        pos[i].x += f[i].x * scale;
        pos[i].y += f[i].y * scale;
      }
      t *= 0.96;
    }

    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    pos.forEach((p) => {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    });
    const pad = 46;
    const s = Math.min((W - 2 * pad) / Math.max(1, maxX - minX),
                       (H - 2 * pad) / Math.max(1, maxY - minY), 1.8);
    const ox = (W - (maxX - minX) * s) / 2;
    const oy = (H - (maxY - minY) * s) / 2;
    pos.forEach((p, i) => {
      nodes[i].x = (p.x - minX) * s + ox;
      nodes[i].y = (p.y - minY) * s + oy;
    });
  }

  function renderGraph() {
    const host = $("#graph-svg");
    empty(host);
    const nodes = Ag.graph.nodes;
    const edges = Ag.graph.edges;
    if (!nodes.length) {
      host.appendChild(el("div", "placeholder", "no vault nodes"));
      buildLegend();
      return;
    }
    layoutGraph(nodes, edges);

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 760 440");

    edges.forEach((pair) => {
      const line = document.createElementNS(svgNS, "line");
      line.setAttribute("class", "g-edge");
      line.setAttribute("data-a", pair[0]);
      line.setAttribute("data-b", pair[1]);
      svg.appendChild(line);
      graphEls.edges.set(pair[0] + "|" + pair[1], line);
    });

    nodes.forEach((nd) => {
      const g = document.createElementNS(svgNS, "g");
      g.setAttribute("class", "g-node");
      g.setAttribute("data-name", nd.name);
      g.setAttribute("transform", `translate(${nd.x},${nd.y})`);
      const r = Math.min(11, 4 + (nd.degree || 0) * 0.9);
      g.appendChild(circle(r, FOLDER_COLOR[nd.folder] || "#888"));
      if (nd.degree >= 3 || nd.folder === "root") {
        const lbl = document.createElementNS(svgNS, "text");
        lbl.setAttribute("class", "g-label");
        lbl.setAttribute("y", r + 12);
        lbl.setAttribute("text-anchor", "middle");
        lbl.textContent = nd.name.replace(/^Agent_/, "");
        g.appendChild(lbl);
      }
      svg.appendChild(g);
      graphEls.nodes.set(nd.name, g);
    });
    host.appendChild(svg);
    graphEls.svg = svg;
    buildLegend();
    applyGraphSelection();
  }

  function circle(r, fill) {
    const svgNS = "http://www.w3.org/2000/svg";
    const c = document.createElementNS(svgNS, "circle");
    c.setAttribute("r", r);
    c.setAttribute("fill", fill === "var(--folder-root)" ? "#e6edf3" : fill);
    return c;
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

  function neighborSet(name) {
    const set = new Set([name]);
    Ag.graph.edges.forEach((p) => {
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
    graphEls.edges.forEach((line, key) => {
      if (!sel) { line.classList.remove("hot"); return; }
      const [a, b] = key.split("|");
      line.classList.toggle("hot", a === sel || b === sel);
    });
  }

  function bindGraph() {
    $("#graph-svg").addEventListener("click", (e) => {
      const node = e.target.closest(".g-node");
      if (node) selectNode(node.dataset.name);
    });
    $("#graph-svg").addEventListener("dblclick", (e) => {
      const node = e.target.closest(".g-node");
      if (node) openNodeModal(node.dataset.name);
    });
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
  async function pollState() {
    try {
      const snap = await api("/api/state");
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

  async function loadSessions() {
    try {
      const data = await api("/api/sessions");
      Ag.sessions = data.sessions || {};
      // rebuild any panels to replay history
      buildWorkspace();
    } catch (_) { /* ignore */ }
  }

  async function loadGraph(refresh) {
    const data = await api("/api/vault/graph" + (refresh ? "?refresh=true" : ""));
    Ag.graph = data;
    graphEls = { svg: null, nodes: new Map(), edges: new Map() };
    Ag.selectedNode = Ag.prefs.selected_node;
    renderGraph();
    $("#graph-count").textContent = data.nodes.length + " nodes";
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
    loadAgents().catch((err) => console.error(err));
    loadSessions();
    loadGraph();
    loadTasks();
    openStream();
    setInterval(pollState, 3000);
  }

  window.addEventListener("DOMContentLoaded", init);
})();
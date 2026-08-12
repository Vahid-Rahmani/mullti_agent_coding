/* ─────────────────────────────────────────────────────────────────────
   settings.js — Phase 25 / 25A Settings modal (frontend for /api/settings/*).
   Vanilla JS, no build step. API keys are WRITE-ONLY: typed into password
   inputs, posted in the request body, and never stored, rendered, echoed,
   or returned by the backend. The UI only ever shows Configured / Tested /
   Validation failed / Not configured status.

   Phase 25A: Save Connection stays disabled until a real Test Connection
   succeeds; the AI Models section is fed by saved connections (catalog),
   and discovered models become selectable for agents.
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
      throw Object.assign(new Error((data && data.detail) || res.statusText),
                          { status: res.status, data });
    }
    return data;
  }
  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }
  function del(path) { return api(path, { method: "DELETE" }); }

  const SECTION_LABEL = {
    general: "General", connections: "AI Connections", models: "Models",
    agents: "Agents", modes: "Agent Modes", graph: "Graph", security: "Security",
  };
  const STATUS_LABEL = {
    not_configured: "Not configured",
    configured: "Configured",
    tested: "Tested",
    validation_failed: "Validation failed",
  };
  const state = {
    meta: null, connections: [], agents: [], available: [], catalog: [],
  };

  /* ── open / close ─────────────────────────────────────────────── */
  function open() {
    $("#settings-backdrop").classList.remove("hidden");
    loadMeta().then(() => render()).catch(() => render());
  }
  function close() {
    $("#settings-backdrop").classList.add("hidden");
    $$(".skey").forEach((i) => { i.value = ""; });   // never persist keys in the DOM
  }
  function activeSec() {
    const active = $("#settings-nav .settings-nav-btn.active");
    return active ? active.dataset.sec : "general";
  }

  async function loadMeta() {
    if (state.meta) return state.meta;
    try {
      const d = await api("/api/settings");
      const c = await api("/api/settings/connections");
      const m = await api("/api/settings/models");
      state.meta = d;
      state.connections = c.providers || [];
      state.agents = m.agents || [];
      state.available = m.available || [];
    } catch (_) {
      state.meta = state.meta || {
        sections: Object.keys(SECTION_LABEL), simple_providers: [], vault: "",
      };
    }
    return state.meta;
  }

  function buildNav(sec) {
    const nav = $("#settings-nav");
    empty(nav);
    (state.meta.sections || Object.keys(SECTION_LABEL)).forEach((s) => {
      const b = el("button", "settings-nav-btn" + (s === sec ? " active" : ""),
                   SECTION_LABEL[s] || s);
      b.dataset.sec = s;
      b.addEventListener("click", () => render(s));
      nav.appendChild(b);
    });
  }

  function render(sec) {
    sec = sec || activeSec();
    buildNav(sec);
    const content = $("#settings-content");
    empty(content);
    const view = {
      general: viewGeneral, connections: viewConnections, models: viewModels,
      agents: viewAgents, modes: viewModes, graph: viewGraph, security: viewSecurity,
    }[sec];
    const node = view ? view() : el("div", "muted", "no such section");
    if (node && typeof node.then === "function") node.then((n) => content.appendChild(n));
    else if (node) content.appendChild(node);
  }

  function setRow(label, input) {
    const wrap = el("div", "set-row");
    wrap.appendChild(el("label", null, label));
    wrap.appendChild(input);
    return wrap;
  }

  function statusDot(status) {
    const cls = (status === "tested" || status === "discovered" || status === true) ? "ok"
      : (status === "validation_failed" || status === "unavailable") ? "err"
      : status === "configured" ? "cfg"
      : "off";
    return el("span", "dot " + cls);
  }

  /* ── General ──────────────────────────────────────────────────── */
  function viewGeneral() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "General"));
    s.appendChild(el("span", "muted", "Control-plane defaults."));
    const vault = el("input");
    vault.value = state.meta.vault || "—";
    vault.disabled = true;
    s.appendChild(setRow("Vault (read-only)", vault));
    const host = el("input");
    host.value = window.location.host;
    host.disabled = true;
    s.appendChild(setRow("Dashboard", host));
    s.appendChild(el("p", "set-note",
      "Agent identity and models are managed in the Models and Agent Modes sections. " +
      "API keys live only in the OpenCode auth store — never in this repository."));
    return s;
  }

  /* ── AI Connections ───────────────────────────────────────────── */
  function viewConnections() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "AI Connections"));
    s.appendChild(el("span", "muted",
      "Simple: pick a provider, paste an API key. Advanced: custom endpoints with Base URL. " +
      "Save unlocks after a successful Test Connection."));
    const list = el("div");
    state.connections.forEach((c) => list.appendChild(connCard(c)));
    s.appendChild(list);
    const add = el("button", "btn primary", "+ Add Connection");
    const wizardHost = el("div");
    add.addEventListener("click", () => {
      add.classList.add("hidden");
      wizardHost.appendChild(connectionWizard(() => {
        wizardHost.innerHTML = "";
        add.classList.remove("hidden");
      }));
    });
    s.appendChild(add);
    s.appendChild(wizardHost);
    return s;
  }

  function connCard(c) {
    const card = el("div", "conn-card");
    card.appendChild(statusDot(c.status));
    card.appendChild(el("span", "conn-name", c.name));
    card.appendChild(el("span", "conn-kind", c.kind));
    card.appendChild(el("span", "conn-status",
      STATUS_LABEL[c.status] || (c.configured ? "Configured" : "Not configured")));
    card.appendChild(el("span", "spacer"));
    if (c.configured) {
      const rm = el("button", "icon-btn", "✕");
      rm.title = "Remove key";
      rm.addEventListener("click", async () => {
        try {
          await del(`/api/settings/security/keys/${encodeURIComponent(c.id)}`);
          await refreshConnections();
        } catch (err) { console.error(err); }
      });
      card.appendChild(rm);
    }
    return card;
  }

  async function refreshConnections() {
    try {
      state.connections = (await api("/api/settings/connections")).providers || [];
    } catch (_) { /* keep last known */ }
    render("connections");
  }

  function connectionWizard(onDone) {
    const box = el("div", "conn-wizard");
    box.appendChild(el("h4", null, "Add Connection"));

    const modeSel = el("select");
    [["simple", "Simple API Connection"], ["advanced", "Advanced / OpenCode Provider"]]
      .forEach(([v, l]) => {
        const o = el("option", null, l);
        o.value = v;
        modeSel.appendChild(o);
      });
    box.appendChild(setRow("Connection mode", modeSel));

    const provSel = el("select");
    (state.meta.simple_providers || []).forEach((p) => {
      const o = el("option", null, p.name);
      o.value = p.id;
      provSel.appendChild(o);
    });
    box.appendChild(setRow("Provider", provSel));

    const key = el("input");
    key.type = "password";
    key.className = "skey";
    key.autocomplete = "off";
    key.placeholder = "API key — stored only in the OpenCode auth store";
    box.appendChild(setRow("API key", key));

    const adv = el("div", "adv-fields hidden");
    const baseUrl = el("input");
    baseUrl.placeholder = "https://api.example.com/v1";
    const authSel = el("select");
    ["Bearer", "x-api-key"].forEach((a) => {
      const o = el("option", null, a);
      o.value = a;
      authSel.appendChild(o);
    });
    const defModel = el("input");
    defModel.placeholder = "provider/model (optional)";
    adv.appendChild(el("span", "adv-tag", "Advanced"));
    adv.appendChild(setRow("Base URL", baseUrl));
    adv.appendChild(setRow("Authentication", authSel));
    adv.appendChild(setRow("Default model", defModel));
    box.appendChild(adv);

    const status = el("div", "conn-status-line");
    const chips = el("div", "model-chips");
    const selected = new Set();
    let testedOk = false;          // Save stays disabled until real validation succeeds

    const testBtn = el("button", "btn", "Test Connection");
    const discBtn = el("button", "btn", "Discover Models");
    const saveBtn = el("button", "btn primary", "Save Connection");
    discBtn.disabled = true;
    saveBtn.disabled = true;

    function setStatus(cls, text) {
      status.className = "conn-status-line" + (cls ? " " + cls : "");
      status.textContent = text || "";
    }
    function updateSaveEnabled() { saveBtn.disabled = !testedOk; }
    function invalidate() {
      testedOk = false;
      setStatus("", "");
      updateSaveEnabled();
    }
    function payload() {
      const models = Array.from(selected);
      if (modeSel.value === "advanced" && defModel.value.trim()) {
        models.push(defModel.value.trim());
      }
      return {
        provider: provSel.value,
        mode: modeSel.value,
        key: key.value || null,
        base_url: baseUrl.value.trim() || null,
        auth: authSel.value,
        models,
      };
    }

    modeSel.addEventListener("change", () => {
      adv.classList.toggle("hidden", modeSel.value !== "advanced");
      invalidate();
    });
    provSel.addEventListener("change", invalidate);
    key.addEventListener("input", invalidate);
    baseUrl.addEventListener("input", invalidate);
    authSel.addEventListener("change", invalidate);
    defModel.addEventListener("input", invalidate);

    const actions = el("div", "wizard-actions");
    actions.appendChild(testBtn);
    actions.appendChild(discBtn);
    actions.appendChild(saveBtn);
    box.appendChild(actions);
    box.appendChild(status);
    box.appendChild(chips);
    const cancel = el("button", "btn", "Cancel");
    cancel.addEventListener("click", onDone);
    box.appendChild(cancel);

    testBtn.addEventListener("click", async () => {
      setStatus("", "testing…");
      testBtn.disabled = true;
      try {
        const r = await post("/api/settings/connections/test", payload());
        testedOk = !!r.ok;
        setStatus(r.ok ? "ok" : "err", r.ok ? "✓ " + r.detail : "✕ " + r.detail);
        discBtn.disabled = !r.ok;
        updateSaveEnabled();
      } catch (err) {
        testedOk = false;
        setStatus("err", "✕ " + err.message);
        updateSaveEnabled();
      } finally {
        testBtn.disabled = false;
      }
    });

    discBtn.addEventListener("click", async () => {
      setStatus("", "discovering models…");
      discBtn.disabled = true;
      try {
        const r = await post("/api/settings/connections/discover", payload());
        empty(chips);
        if (!r.models.length) {
          chips.appendChild(el("span", "muted", "no models discovered — add one manually below"));
        }
        r.models.forEach((m) => {
          const b = el("button", "f-chip" + (selected.has(m.id) ? " active" : ""),
                       m.id + (m.source === "configured" ? " •" : ""));
          b.title = m.source === "configured"
            ? "configured in opencode.json"
            : "discovered from provider";
          b.addEventListener("click", () => {
            if (selected.has(m.id)) selected.delete(m.id);
            else selected.add(m.id);
            b.classList.toggle("active", selected.has(m.id));
          });
          chips.appendChild(b);
        });
        chips.appendChild(manualModelRow(provSel, selected, setStatus));
      } catch (err) {
        setStatus("err", "✕ " + err.message);
      } finally {
        discBtn.disabled = false;
      }
    });

    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      try {
        const r = await post("/api/settings/connections/save", payload());
        if (r.configured) {
          setStatus("ok", "✓ saved — key stored in the OpenCode auth store");
        } else if (r.key_pending) {
          setStatus("", "key not stored automatically — run: " + (r.command || "opencode auth login"));
        } else {
          setStatus("ok", "✓ saved");
        }
        refreshConnections();
        setTimeout(onDone, 1200);
      } catch (err) {
        setStatus("err", "✕ " + err.message);
        saveBtn.disabled = false;
      }
    });

    return box;
  }

  function manualModelRow(provSel, selected, setStatus) {
    const wrap = el("div", "set-row");
    wrap.appendChild(el("label", null, "Manual model"));
    const line = el("div", "wizard-actions");
    const mi = el("input");
    mi.placeholder = "model-id or provider/model-id";
    const addBtn = el("button", "btn", "Add");
    line.appendChild(mi);
    line.appendChild(addBtn);
    wrap.appendChild(line);
    addBtn.addEventListener("click", async () => {
      const id = mi.value.trim();
      if (!id) return;
      try {
        await post(`/api/settings/connections/${encodeURIComponent(provSel.value)}/models`,
                    { model: id });
        if (!selected.has(id)) {
          selected.add(id);
          const b = el("button", "f-chip active", id);
          b.addEventListener("click", () => { selected.delete(id); b.remove(); });
          wrap.parentElement.appendChild(b);
        }
        mi.value = "";
      } catch (err) {
        setStatus("err", "✕ " + err.message);
      }
    });
    return wrap;
  }

  /* ── Models: catalog (from saved connections) + agent assignment ─ */
  async function viewModels() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "Models"));
    s.appendChild(el("span", "muted",
      "The catalog is fed by your saved connections. Discover models, then assign one to each agent — " +
      "saves update the agent spec and opencode.json atomically."));
    let catalog = [];
    try {
      catalog = ((await api("/api/settings/models/catalog")).providers) || [];
    } catch (_) { /* catalog stays empty; agent table still renders */ }
    state.catalog = catalog;
    s.appendChild(catalogSection(catalog));
    s.appendChild(agentModelTable());
    return s;
  }

  function catalogSection(providers) {
    const wrap = el("div");
    wrap.appendChild(el("h4", null, "Model catalog"));
    if (!providers.length) {
      wrap.appendChild(el("div", "muted", "no providers yet — add a connection first"));
    }
    providers.forEach((p) => wrap.appendChild(catalogProvider(p)));
    const refreshAll = el("button", "btn", "Discover / Refresh all");
    refreshAll.addEventListener("click", () => render("models"));   // re-fetches the live catalog
    wrap.appendChild(refreshAll);
    return wrap;
  }

  function catalogProvider(p) {
    const box = el("div", "set-row");
    const head = el("div", "wizard-actions");
    const avail = p.configured
      ? (p.available === false ? "unavailable" : p.available === true ? "discovered" : "configured")
      : "not configured";
    head.appendChild(statusDot(avail));
    head.appendChild(el("span", "conn-name", p.name));
    head.appendChild(el("span", "conn-kind", p.kind));
    head.appendChild(el("span", "conn-status",
      p.available === false ? "unavailable — " + (p.error || "discovery failed") : avail));
    if (p.configured) {
      const disc = el("button", "btn", "Discover");
      disc.title = "Discover models from this connection";
      disc.addEventListener("click", () => render("models"));
      head.appendChild(disc);
    }
    box.appendChild(head);
    const chips = el("div", "model-chips");
    if (!p.models.length) {
      chips.appendChild(el("span", "muted",
        p.configured ? "no models yet — click Discover" : "connect this provider first"));
    }
    p.models.forEach((m) => {
      const c = el("span", "f-chip" + (m.enabled ? " active" : ""), m.display_name);
      c.title = (m.enabled ? "enabled · " : "discovered · ") + m.model_id;
      chips.appendChild(c);
    });
    box.appendChild(chips);
    return box;
  }

  function agentModelTable() {
    const wrap = el("div");
    wrap.appendChild(el("h4", null, "Agent model assignment"));
    const table = el("table", "sec-table");
    const thead = el("thead");
    const htr = el("tr");
    ["Agent", "Model", ""].forEach((t) => htr.appendChild(el("th", null, t)));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el("tbody");

    // catalog models (canonical provider/model ids) are selectable for agents
    const opts = new Map(state.available.map((m) => [m.id, m.name]));
    (state.catalog || []).forEach((p) =>
      p.models.forEach((m) => opts.set(m.model_id, m.display_name + " (" + p.name + ")")));

    state.agents.forEach((a) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, `${a.name} (${a.tag.toUpperCase()})`));
      const td = el("td");
      const sel = el("select");
      opts.set(a.model, a.model);
      Array.from(opts.entries())
        .sort((x, y) => x[0].localeCompare(y[0]))
        .forEach(([id, name]) => {
          const o = el("option", null, name);
          o.value = id;
          if (id === a.model) o.selected = true;
          sel.appendChild(o);
        });
      const custom = el("option", null, "custom…");
      custom.value = "__custom__";
      sel.appendChild(custom);
      td.appendChild(sel);
      tr.appendChild(td);
      const act = el("td");
      const save = el("button", "btn", "Save");
      const badge = el("span", "verify-badge");
      save.addEventListener("click", async () => {
        save.disabled = true;
        let model = sel.value;
        if (model === "__custom__") {
          const typed = window.prompt("Model id (provider/model):", a.model || "");
          if (!typed) { save.disabled = false; return; }
          model = typed.trim();
        }
        try {
          const r = await post("/api/settings/models", { agent: a.agent, model });
          badge.className = "verify-badge ok";
          badge.textContent = "saved ✓";
          a.model = r.model;
          const fresh = await api("/api/settings/models");
          state.agents = fresh.agents || state.agents;
          state.available = fresh.available || state.available;
          const existing = Array.from(sel.options).some((o) => o.value === r.model);
          if (!existing) {
            const o = el("option", null, r.model);
            o.value = r.model;
            sel.insertBefore(o, custom);
          }
          sel.value = r.model;
        } catch (err) {
          badge.className = "verify-badge err";
          badge.textContent = err.message;
        } finally {
          save.disabled = false;
        }
      });
      act.appendChild(save);
      act.appendChild(badge);
      tr.appendChild(act);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  /* ── Agents (read-only roster) ────────────────────────────────── */
  function viewAgents() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "Agents"));
    s.appendChild(el("span", "muted", "Roster from the agent registry (read-only here)."));
    const table = el("table", "sec-table");
    const thead = el("thead");
    const htr = el("tr");
    ["Tag", "Name", "Agent key", "Model", "Mode"].forEach((t) => htr.appendChild(el("th", null, t)));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el("tbody");
    state.agents.forEach((a) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, a.tag.toUpperCase()));
      tr.appendChild(el("td", null, a.name));
      tr.appendChild(el("td", null, a.agent || "—"));
      tr.appendChild(el("td", null, a.model || "—"));
      tr.appendChild(el("td", null, a.mode || "—"));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    s.appendChild(table);
    return s;
  }

  /* ── Agent Modes (opencode's real mode field) ─────────────────── */
  function viewModes() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "Agent Modes"));
    s.appendChild(el("span", "muted",
      "OpenCode's real per-agent mode: primary, subagent, or all (standalone + subagent). " +
      "Master is not configurable."));
    state.agents.filter((a) => a.agent).forEach((a) => {
      const card = el("div", "set-row");
      card.appendChild(el("label", null, `${a.name} (${a.tag.toUpperCase()})`));
      const line = el("div", "wizard-actions");
      const sel = el("select");
      ["primary", "subagent", "all"].forEach((m) => {
        const o = el("option", null, m);
        o.value = m;
        if (m === a.mode) o.selected = true;
        sel.appendChild(o);
      });
      const desc = el("input");
      desc.value = a.description || "";
      desc.placeholder = "description";
      const save = el("button", "btn", "Save");
      const badge = el("span", "verify-badge");
      save.addEventListener("click", async () => {
        save.disabled = true;
        try {
          await post(`/api/settings/agents/${encodeURIComponent(a.agent)}/mode`, {
            mode: sel.value,
            description: desc.value.trim() || null,
          });
          a.mode = sel.value;
          a.description = desc.value;
          badge.className = "verify-badge ok";
          badge.textContent = "saved ✓";
        } catch (err) {
          badge.className = "verify-badge err";
          badge.textContent = err.message;
        } finally {
          save.disabled = false;
        }
      });
      line.appendChild(sel);
      line.appendChild(desc);
      line.appendChild(save);
      line.appendChild(badge);
      card.appendChild(line);
      s.appendChild(card);
    });
    return s;
  }

  /* ── Graph (existing preferences only) ────────────────────────── */
  function viewGraph() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "Graph"));
    s.appendChild(el("span", "muted", "Preferences already supported by the graph view."));
    const h = el("input");
    h.type = "number";
    h.min = 140;
    h.max = 560;
    h.step = 10;
    h.value = 300;
    const mm = el("input");
    mm.type = "checkbox";
    mm.checked = true;
    api("/api/prefs").then((p) => {
      if (p.graph_h) h.value = p.graph_h;
      if (typeof p.minimap_on === "boolean") mm.checked = p.minimap_on;
    }).catch(() => { /* defaults stand */ });
    s.appendChild(setRow("Graph height (px, 140–560)", h));
    s.appendChild(setRow("Show minimap", mm));
    const save = el("button", "btn primary", "Save");
    const badge = el("span", "verify-badge");
    const line = el("div", "wizard-actions");
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        await post("/api/prefs", {
          graph_h: Math.max(140, Math.min(560, Number(h.value) || 300)),
          minimap_on: mm.checked,
        });
        badge.className = "verify-badge ok";
        badge.textContent = "saved ✓";
      } catch (err) {
        badge.className = "verify-badge err";
        badge.textContent = err.message;
      } finally {
        save.disabled = false;
      }
    });
    line.appendChild(save);
    line.appendChild(badge);
    s.appendChild(line);
    return s;
  }

  /* ── Security ─────────────────────────────────────────────────── */
  function viewSecurity() {
    const s = el("div", "set-section");
    s.appendChild(el("h3", null, "Security"));
    s.appendChild(el("span", "muted",
      "API keys are stored only in the OpenCode auth store — never in this repository, " +
      "never in the browser, never shown again."));
    const table = el("table", "sec-table");
    const thead = el("thead");
    const htr = el("tr");
    ["Provider", "Key status", ""].forEach((t) => htr.appendChild(el("th", null, t)));
    thead.appendChild(htr);
    table.appendChild(thead);
    const tbody = el("tbody");
    state.connections.forEach((c) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, c.name));
      const st = el("td");
      st.appendChild(statusDot(c.configured));
      st.appendChild(el("span", null, c.configured ? "Configured" : "Not configured"));
      tr.appendChild(st);
      const act = el("td");
      if (c.configured) {
        const rm = el("button", "btn danger", "Remove key");
        rm.addEventListener("click", async () => {
          try {
            await del(`/api/settings/security/keys/${encodeURIComponent(c.id)}`);
            await refreshConnections();
          } catch (err) { console.error(err); }
        });
        act.appendChild(rm);
      }
      tr.appendChild(act);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    s.appendChild(table);
    s.appendChild(el("p", "set-note",
      "Keys are write-only: they can be added or removed but never displayed. " +
      "To log in interactively, run: opencode auth login <provider>"));
    return s;
  }

  /* ── wiring ───────────────────────────────────────────────────── */
  function bind() {
    const closeBtn = $("#settings-close");
    if (closeBtn) closeBtn.addEventListener("click", close);
    const backdrop = $("#settings-backdrop");
    if (backdrop) {
      backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && backdrop && !backdrop.classList.contains("hidden")) close();
    });
  }

  window.MACSettings = { open, close };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();

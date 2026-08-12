"""Web dashboard — Obsidian-inspired UI for the MultiAgentCoding control plane.

Primary human interface. Replaces the ZOVA retro terminal as the default view
(the terminal remains available as a fallback). The dashboard reuses the
existing backend unchanged: the in-process ``RunHub`` for ad-hoc agent
dispatch, ``VaultBridge``/``ContextResolver`` for vault reads and safe writes,
and the real Orchestrator CLI for task execution.

Module layout:
    server.py   — FastAPI app factory + uvicorn entry (``--smoke``)
    routes.py   — REST/SSE endpoints (thin layer over core)
    state.py    — WebState: drains HUB events into per-agent sessions
    graph.py    — VaultGraph: read-only node/edge model of the managed vault
    settings.py — Settings facade: AI connections, discovery, auth-store keys
    static/     — index.html · app.css · app.js · settings.js (frontend)
"""
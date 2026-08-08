#!/usr/bin/env python3
"""
MultiAgentCoding — AI Agent Workspace Web UI (Dyad-style)

A browser-based replacement for the desktop GUI. FastAPI + Tailwind (CDN) +
vanilla JS in a single self-contained file. Deep monochromatic dark theme with
electric-blue / lime accents, icon sidebar navigation, a center chat workplane
with cascading Model/Mode dropdowns and collapsible thoughts, and a right-side
Terminal Logs console streaming all agent output (stdout, stderr, code
previews, responses) linearly.

Architecture:
  * ``WebHub`` — thread-safe state for agent runs (statuses, per-tag log
    buffers, subprocess handles). Mirrors the desktop GUI's run semantics:
    ``opencode run --agent <a> --auto [-m <model>] [-agent mode] "<prompt>"``.
  * SSE endpoint ``/api/stream`` — pushes status + line events to the browser
    (client tracks a per-tag cursor, so late joiners get a full snapshot).
  * Provider CRUD ``/api/providers`` — reads/writes the ``provider`` block of
    ``opencode.json`` atomically (backup + temp file + replace). API keys are
    NEVER written here; they live in ``~/.local/share/opencode/auth.json``.

Usage:
    python scripts/web_app.py [--port 8501] [--no-browser]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from urllib.parse import urlparse

# Reuse the desktop GUI's pure logic (constants + command builder).
from unified_app import (
    AGENTS,
    AUTO_MODE,
    AUTO_MODEL,
    MODE_OPTIONS_BY_MODEL,
    MODEL_OPTIONS,
    PROJECT_ROOT,
    TAG_COLORS,
    _build_run_command,
    _opencode_command,
    _strip_ansi,
)

# --------------------------------------------------------------------------- config

DEFAULT_PORT = 8501
CONFIG_PATH = PROJECT_ROOT / "opencode.json"

# Read-only source of API keys (never written by this app, never logged).
AUTH_PATH = Path(os.path.expanduser("~/.local/share/opencode/auth.json"))

# Built-in provider catalog: id, display name, adapter npm package, base URL,
# and the conventional env var that holds the API key.
BUILTIN_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "npm": "@ai-sdk/openai",
        "baseURL": "https://api.openai.com/v1",
        "envVar": "OPENAI_API_KEY",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "npm": "@ai-sdk/anthropic",
        "baseURL": "https://api.anthropic.com/v1",
        "envVar": "ANTHROPIC_API_KEY",
    },
    {
        "id": "google",
        "name": "Google Vertex",
        "npm": "@ai-sdk/google-vertex",
        "baseURL": "https://us-central1-aiplatform.googleapis.com/v1",
        "envVar": "GOOGLE_API_KEY",
    },
]


def _builtin_provider(name: str) -> dict | None:
    """Return the built-in provider block for ``name`` (by id), or None."""
    for provider in BUILTIN_PROVIDERS:
        if provider["id"] == name:
            return provider
    return None


def _effective_env_var(name: str, env_var: str | None) -> str | None:
    """Custom env var name, falling back to the built-in default for the id."""
    if env_var:
        return env_var
    provider = _builtin_provider(name)
    return provider.get("envVar") if provider else None


def _is_local_base_url(base_url: str | None) -> bool:
    """True when the base URL points at a local host (no API key required)."""
    if not base_url:
        return False
    try:
        host = urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host == "localhost" or host == "0.0.0.0" or host.startswith("127.")


def _auth_store() -> dict:
    """Read auth.json (read-only). Never prints or returns key values in logs.

    Missing or corrupt files yield an empty dict instead of raising.
    """
    if not AUTH_PATH.exists():
        return {}
    try:
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_api_key(name: str, env_var: str | None = None) -> tuple[str | None, str]:
    """Resolve an API key for ``name`` -> (key, source).

    Precedence: env var (custom ``env_var`` or the built-in default) when set
    and non-empty -> ``env``; auth.json entry for ``name`` -> ``auth``;
    otherwise (None, "none"). Empty-string env vars count as unset.
    """
    env_name = _effective_env_var(name, env_var)
    if env_name:
        value = os.environ.get(env_name, "")
        if value:
            return value, "env"
    entry = _auth_store().get(name)
    key = (entry or {}).get("key", "")
    if key:
        return key, "auth"
    return None, "none"


def provider_status(
    name: str, env_var: str | None = None, base_url: str | None = None
) -> dict:
    """Provider readiness -> {status, source, envVar}.

    status: ready | needs-setup | local. "local" applies when the provider
    needs no key (e.g. ollama-style local base URL). source: auth | env | none.
    """
    if base_url is None:
        provider = _builtin_provider(name)
        base_url = provider.get("baseURL") if provider else None
    if _is_local_base_url(base_url):
        return {"status": "local", "source": "none", "envVar": _effective_env_var(name, env_var)}
    key, source = resolve_api_key(name, env_var)
    return {
        "status": "ready" if key else "needs-setup",
        "source": source,
        "envVar": _effective_env_var(name, env_var),
    }


def _backup_path() -> Path:
    """Backup sits next to the config file (follows CONFIG_PATH in tests)."""
    return CONFIG_PATH.with_suffix(".json.bak")

STATUS_IDLE = "idle"
STATUS_THINKING = "thinking"
STATUS_ACTIVE = "active"
STATUS_ERROR = "error"

# Fallback modes for models not present in MODE_OPTIONS_BY_MODEL.
DEFAULT_MODES = ["architect", "build", "analyze", "plan", "review", "compact"]

# Dyad-style palette (mirrors the Tailwind theme).
BG = "#0B0E14"
PANEL = "#0F172A"
PANEL_ALT = "#1E293B"
BORDER = "#293548"
ACCENT = "#38BDF8"  # electric blue
ACCENT_LIME = "#A3E635"
TEXT = "#E2E8F0"
MUTED = "#94A3B8"
ERROR = "#F87171"

AGENT_ICONS = {tag: str(i + 1) for i, (tag, _, _) in enumerate(AGENTS)}
AGENT_ICONS["master"] = "⌂"
AGENT_ICONS["settings"] = "⚙"

# --------------------------------------------------------------------------- hub


class WebHub:
    """Thread-safe shared state for live agent runs.

    Events are appended to an ordered list with a monotonically increasing
    sequence number so SSE clients can resume from any cursor.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.statuses: dict[str, str] = {tag: STATUS_IDLE for tag, _, _ in AGENTS}
        self.buffers: dict[str, list[str]] = {tag: [] for tag, _, _ in AGENTS}
        self.buffers["master"] = []
        self.events: list[dict] = []  # {"seq", "tag", "kind", "text"}
        self.seq = 0
        self.procs: dict[str, subprocess.Popen] = {}
        self.running = 0
        self.workspace: Path = PROJECT_ROOT

    # ------------------------------------------------------------ state writes

    def _emit(self, tag: str, kind: str, text: str) -> None:
        with self.lock:
            self.seq += 1
            self.events.append(
                {"seq": self.seq, "tag": tag, "kind": kind, "text": _strip_ansi(text)}
            )

    def set_status(self, tag: str, status: str) -> None:
        with self.lock:
            self.statuses[tag] = status
        self._emit(tag, "status", status)

    def append_line(self, tag: str, text: str) -> None:
        with self.lock:
            self.buffers[tag].append(text)
        self._emit(tag, "line", text)

    def append_error(self, tag: str, text: str) -> None:
        with self.lock:
            self.buffers[tag].append(text)
        self._emit(tag, "error", text)

    def clear(self) -> None:
        with self.lock:
            for buf in self.buffers.values():
                buf.clear()
        self._emit("master", "line", "── logs cleared ──")

    # ------------------------------------------------------------ running

    def resolve(self, tag: str, overrides: dict[str, dict[str, str]]) -> tuple[str | None, str]:
        """Resolve (model, mode) for a tab, mirroring the desktop GUI.

        Priority: the agent tab's own override, then the master override,
        then None / AUTO_MODE.
        """
        tab = overrides.get(tag, {})
        master = overrides.get("master", {})
        tab_model = tab.get("model")
        master_model = master.get("model")
        if tab_model and tab_model != AUTO_MODEL:
            model = tab_model
        elif master_model and master_model != AUTO_MODEL:
            model = master_model
        else:
            model = None
        tab_mode = tab.get("mode")
        master_mode = master.get("mode")
        if tab_mode and tab_mode != AUTO_MODE:
            mode = tab_mode
        elif master_mode and master_mode != AUTO_MODE:
            mode = master_mode
        else:
            mode = AUTO_MODE
        return model, mode

    def run(self, prompt: str, overrides: dict[str, dict[str, str]]) -> None:
        """Spawn one worker thread per agent (mirrors desktop RUN COMMAND)."""
        if not prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt must not be empty.")
        self.append_line("master", f"▶ {prompt}")
        with self.lock:
            self.running += len(AGENTS)
        for tag, name, agent in AGENTS:
            model, mode = self.resolve(tag, overrides)
            self.set_status(tag, STATUS_THINKING)
            threading.Thread(
                target=self._run_agent,
                args=(tag, name, agent, prompt, model, mode),
                name=f"web-{tag}",
                daemon=True,
            ).start()

    def _run_agent(
        self,
        tag: str,
        name: str,
        agent: str,
        prompt: str,
        model: str | None,
        mode: str | None,
    ) -> None:
        try:
            exe = _opencode_command()
            if not exe:
                raise FileNotFoundError(
                    "opencode executable not found on PATH. Install opencode or "
                    "add it to PATH before running the web UI."
                )
            cmd = _build_run_command(exe, agent, prompt, model, mode)
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            with self.lock:
                self.procs[tag] = proc
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    self.append_line(tag, f"[{tag} {name}] {line}")
                    self.set_status(tag, STATUS_ACTIVE)
            returncode = proc.wait()
            with self.lock:
                self.procs.pop(tag, None)
            if returncode != 0:
                self.append_error(tag, f"[{tag} {name}] exit code {returncode}")
                self.set_status(tag, STATUS_ERROR)
            else:
                self.set_status(tag, STATUS_IDLE)
        except Exception as exc:  # noqa: BLE001 — surface in UI
            self.append_error(tag, f"[{tag} {name}] ERROR: {exc}")
            self.set_status(tag, STATUS_ERROR)
        finally:
            with self.lock:
                self.running = max(0, self.running - 1)

    def terminate_all(self) -> None:
        with self.lock:
            procs = list(self.procs.values())
            self.procs.clear()
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        self.append_line("master", "── terminated ──")


HUB = WebHub()

# --------------------------------------------------------------------------- opencode.json provider CRUD


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"opencode.json is invalid JSON: {exc}") from exc


def _write_config(config: dict) -> None:
    """Atomic write with backup: preserve the rest of opencode.json."""
    backup = _backup_path()
    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, backup)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def list_providers() -> list[dict]:
    config = _load_config()
    providers = config.get("provider", {})
    result = []
    for name, block in providers.items():
        options = block.get("options", {})
        result.append(
            {
                "name": name,
                "npm": block.get("npm", ""),
                "baseURL": options.get("baseURL", ""),
                "models": sorted(block.get("models", {}).keys()),
            }
        )
    return result


def add_provider(name: str, npm: str, base_url: str, models: list[str]) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Provider name must not be empty.")
    config = _load_config()
    if name in config.get("provider", {}):
        raise HTTPException(status_code=409, detail=f"Provider '{name}' already exists.")
    config.setdefault("provider", {})[name] = {
        "npm": npm or "@ai-sdk/openai-compatible",
        "name": name,
        "options": {"baseURL": base_url} if base_url else {},
        "models": {m: {"name": m} for m in models if m.strip()},
    }
    _write_config(config)
    return {"ok": True, "name": name}


def update_provider(name: str, npm: str | None, base_url: str | None, models: list[str] | None) -> dict:
    config = _load_config()
    providers = config.setdefault("provider", {})
    if name not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")
    block = providers[name]
    if npm is not None:
        block["npm"] = npm or "@ai-sdk/openai-compatible"
    if base_url is not None:
        block.setdefault("options", {})["baseURL"] = base_url
    if models is not None:
        block["models"] = {m: {"name": m} for m in models if m.strip()}
    _write_config(config)
    return {"ok": True, "name": name}


def delete_provider(name: str) -> dict:
    config = _load_config()
    providers = config.get("provider", {})
    if name not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")
    del providers[name]
    _write_config(config)
    return {"ok": True, "name": name}


def build_catalog() -> dict:
    """Model + mode options for the cascading dropdowns.

    Base: the desktop GUI's MODEL_OPTIONS / MODE_OPTIONS_BY_MODEL, merged with
    any models discovered from opencode.json providers. Unknown models fall
    back to DEFAULT_MODES.
    """
    models = list(MODEL_OPTIONS)
    modes_by_model: dict[str, list[str]] = {k: list(v) for k, v in MODE_OPTIONS_BY_MODEL.items()}
    for provider in list_providers():
        for model_id in provider["models"]:
            if model_id not in models:
                models.append(model_id)
            modes_by_model.setdefault(model_id, list(DEFAULT_MODES))
    return {
        "models": models,
        "modesByModel": modes_by_model,
        "defaultModes": DEFAULT_MODES,
        "agents": AGENTS,
        "colors": TAG_COLORS,
        "autoModel": AUTO_MODEL,
        "autoMode": AUTO_MODE,
    }


# --------------------------------------------------------------------------- API models


class RunRequest(BaseModel):
    prompt: str
    overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class ProviderIn(BaseModel):
    name: str
    npm: str = ""
    baseURL: str = ""
    models: list[str] = Field(default_factory=list)


class ProviderPatch(BaseModel):
    npm: str | None = None
    baseURL: str | None = None
    models: list[str] | None = None


class WorkspaceIn(BaseModel):
    path: str


# --------------------------------------------------------------------------- app

app = FastAPI(title="MultiAgentCoding Web UI", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE_HTML


@app.get("/api/status")
def api_status() -> dict:
    return {"statuses": HUB.statuses, "running": HUB.running, "workspace": str(HUB.workspace)}


@app.get("/api/catalog")
def api_catalog() -> dict:
    return build_catalog()


@app.post("/api/run")
def api_run(req: RunRequest) -> dict:
    HUB.run(req.prompt, req.overrides)
    return {"ok": True}


@app.post("/api/clear")
def api_clear() -> dict:
    HUB.clear()
    return {"ok": True}


@app.post("/api/terminate")
def api_terminate() -> dict:
    HUB.terminate_all()
    return {"ok": True}


@app.post("/api/workspace")
def api_workspace(req: WorkspaceIn) -> dict:
    p = Path(req.path).expanduser().resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {p}")
    HUB.workspace = p
    return {"ok": True, "workspace": str(p)}


@app.get("/api/providers")
def api_providers() -> list[dict]:
    return list_providers()


@app.post("/api/providers", status_code=201)
def api_providers_add(body: ProviderIn) -> dict:
    return add_provider(body.name, body.npm, body.baseURL, body.models)


@app.put("/api/providers/{name}")
def api_providers_update(name: str, body: ProviderPatch) -> dict:
    return update_provider(name, body.npm, body.baseURL, body.models)


@app.delete("/api/providers/{name}")
def api_providers_delete(name: str) -> dict:
    return delete_provider(name)


@app.get("/api/stream")
async def api_stream() -> StreamingResponse:
    """Server-Sent Events stream.

    Sends an initial snapshot (full per-tag history + statuses) followed by
    incremental events. Clients track their own per-tag cursor.
    """

    async def gen():
        # Per-tag cursor captured at connect time.
        cursors = {tag: len(buf) for tag, buf in HUB.buffers.items()}
        snapshot = {
            "type": "snapshot",
            "statuses": dict(HUB.statuses),
            "history": {tag: list(buf) for tag, buf in HUB.buffers.items()},
        }
        yield f"event: message\ndata: {json.dumps(snapshot)}\n\n"
        last_seq = HUB.seq
        while True:
            await asyncio.sleep(0.15)
            with HUB.lock:
                new_events = [e for e in HUB.events if e["seq"] > last_seq]
                if new_events:
                    last_seq = max(e["seq"] for e in new_events)
                cursors = {tag: len(buf) for tag, buf in HUB.buffers.items()} if new_events else cursors
                # always forward the full history delta by cursor as well
                deltas = {
                    tag: list(HUB.buffers[tag][cursors.get(tag, 0):])
                    for tag in HUB.buffers
                    if len(HUB.buffers[tag]) > cursors.get(tag, 0)
                }
            if new_events or deltas:
                payload = {"type": "delta", "events": new_events, "buffers": deltas}
                yield f"event: message\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- UI (single-file HTML)

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MultiAgentCoding — Agent Workspace</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          bg: "#0B0E14", panel: "#0F172A", panel2: "#1E293B",
          edge: "#293548", accent: "#38BDF8", lime: "#A3E635",
          txt: "#E2E8F0", muted: "#94A3B8", danger: "#F87171",
        },
        fontFamily: {
          sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
          mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "monospace"],
        },
      },
    },
  };
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>
  html, body { height: 100%; }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #293548; border-radius: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  .card { background: #0F172A; border: 1px solid #293548; border-radius: 12px; }
  .dot { width: 9px; height: 9px; border-radius: 9999px; display: inline-block; }
  .dot-idle { background: #475569; }
  .dot-thinking { background: #38BDF8; animation: pulse 1s infinite; }
  .dot-active { background: #A3E635; animation: pulse 1s infinite; }
  .dot-error { background: #F87171; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
  .acc { border: 1px solid #293548; border-radius: 10px; overflow: hidden; }
  .acc-head { cursor: pointer; user-select: none; }
  .acc-body { max-height: 0; overflow: hidden; transition: max-height 0.25s ease; }
  .acc.open .acc-body { max-height: 520px; overflow: auto; }
  select, textarea { background: #0B0E14; border: 1px solid #293548; color: #E2E8F0; }
  select:focus, textarea:focus { outline: none; border-color: #38BDF8; }
  /* API & Models Manager modal inputs: dark grey fields, crisp text, muted placeholders */
  #settings input {
    background: #1E293B;
    border: 1px solid #334155;
    color: #F8FAFC;
    padding: 6px 8px;
  }
  #settings input::placeholder { color: #94A3B8; }
  #settings input:focus { outline: none; border-color: #38BDF8; }
  pre.codeblock { font-family: "JetBrains Mono", monospace; font-size: 12px; line-height: 1.6; }
</style>
</head>
<body class="bg-bg text-txt font-sans h-screen overflow-hidden flex flex-col">

<!-- top bar -->
<div class="flex items-center gap-3 px-4 py-2.5 border-b border-edge bg-panel">
  <button id="btnSidebar" class="text-muted hover:text-txt text-lg leading-none w-7 h-7 rounded hover:bg-panel2 transition" title="Toggle sidebar">☰</button>
  <div class="flex-1 text-sm text-muted truncate">
    <span class="text-txt font-semibold">MultiAgentCoding</span>
    <span class="mx-2 text-edge">|</span>
    <span id="lblWorkspace" class="font-mono text-xs">workspace: …</span>
  </div>
  <button id="btnWorkspace" class="text-xs px-2.5 py-1 rounded border border-edge text-muted hover:text-txt hover:border-accent transition">Change…</button>
  <button id="btnClear" class="text-xs px-2.5 py-1 rounded border border-edge text-muted hover:text-txt transition">Clear</button>
  <button id="btnStop" class="text-xs px-2.5 py-1 rounded border border-edge text-danger hover:text-txt transition">Stop</button>
</div>

<div class="flex flex-1 min-h-0">

  <!-- left icon sidebar -->
  <aside id="sidebar" class="w-14 shrink-0 border-r border-edge bg-panel flex flex-col items-center py-3 gap-1 transition-all duration-200 overflow-hidden">
    <button data-tab="master" class="nav-btn w-10 h-10 rounded-lg text-lg text-muted hover:text-txt hover:bg-panel2 transition" title="Master Console">⌂</button>
    <div class="w-8 border-t border-edge my-1"></div>
    <div id="agentNav" class="flex flex-col items-center gap-1"></div>
    <div class="flex-1"></div>
    <div class="w-8 border-t border-edge my-1"></div>
    <button data-tab="settings" class="nav-btn w-10 h-10 rounded-lg text-lg text-muted hover:text-txt hover:bg-panel2 transition" title="API & Models">⚙</button>
  </aside>

  <!-- center workplane -->
  <main class="flex-1 flex flex-col min-w-0">

    <!-- tab header: cascading model/mode dropdowns + status dot -->
    <div class="flex items-center gap-3 px-4 py-2.5 border-b border-edge bg-panel">
      <span id="lblTab" class="font-semibold text-sm">Master Console</span>
      <span id="tabDot" class="dot dot-idle"></span>
      <div class="flex-1"></div>
      <label class="text-xs text-muted">Model</label>
      <select id="selModel" class="text-xs rounded px-2 py-1.5 w-56"></select>
      <label class="text-xs text-muted ml-2">Mode</label>
      <select id="selMode" class="text-xs rounded px-2 py-1.5 w-44"></select>
    </div>

    <!-- chat messages -->
    <div id="chat" class="flex-1 overflow-y-auto px-4 py-4 space-y-4"></div>

    <!-- quick action pills + input -->
    <div class="border-t border-edge bg-panel px-4 pt-2 pb-3">
      <div class="flex items-center gap-2 mb-2" id="quickActions">
        <span class="text-xs text-muted">Quick actions:</span>
        <button data-pill="Plan the next implementation step for the current project." class="pill">Plan</button>
        <button data-pill="Build / implement the next planned task for the current project." class="pill">Build</button>
        <button data-pill="Review the latest changes in the current project." class="pill">Review</button>
        <button data-pill="Analyze the current project and produce a requirements analysis." class="pill">Analyze</button>
        <button data-pill="Write and run tests for the current project." class="pill">Test</button>
      </div>
      <div class="flex items-end gap-2">
        <textarea id="input" rows="2" placeholder="Message the agent swarm…  (Enter to run, Shift+Enter for newline)" class="flex-1 rounded-xl px-4 py-3 text-sm resize-none"></textarea>
        <button id="btnRun" class="shrink-0 h-11 px-5 rounded-xl bg-accent text-bg font-semibold hover:opacity-90 transition">Run</button>
      </div>
    </div>
  </main>

  <!-- right log console -->
  <aside class="w-96 shrink-0 border-l border-edge bg-panel flex flex-col">
    <div class="px-3 py-2 border-b border-edge text-xs font-semibold text-muted flex items-center gap-2">
      Terminal Logs <span id="canvasTag" class="font-mono text-accent">m1</span>
    </div>
    <div id="canvasOut" class="flex-1 min-h-0 m-2 overflow-auto rounded-lg bg-bg border border-edge p-2 font-mono text-[11px] text-txt leading-relaxed"></div>
  </aside>
</div>

<!-- settings overlay (API & Models) -->
<div id="settings" class="hidden fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6">
  <div class="card w-full max-w-3xl max-h-[85vh] overflow-auto p-5">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">⚙ API &amp; Models Manager</h2>
      <button id="btnSettingsClose" class="text-muted hover:text-txt text-xl leading-none">✕</button>
    </div>
    <p class="text-xs text-muted mb-4">Manages the <code class="font-mono">provider</code> block of <code class="font-mono">opencode.json</code>.
      API keys are never stored here — they live in <code class="font-mono">~/.local/share/opencode/auth.json</code>.</p>
    <div id="providers" class="space-y-3"></div>

    <div class="border-t border-edge mt-4 pt-4">
      <h3 class="text-sm font-semibold mb-2">Add provider</h3>
      <div class="grid grid-cols-2 gap-2">
        <input id="pName" placeholder="name (e.g. openrouter)" class="text-xs rounded px-2 py-1.5">
        <input id="pURL" placeholder="base URL (optional)" class="text-xs rounded px-2 py-1.5">
        <input id="pNpm" placeholder="adapter (default @ai-sdk/openai-compatible)" class="text-xs rounded px-2 py-1.5 col-span-2">
        <input id="pModels" placeholder="models, comma separated (e.g. openrouter/auto, deepseek/deepseek-chat)" class="text-xs rounded px-2 py-1.5 col-span-2">
      </div>
      <button id="btnAddProvider" class="mt-3 px-4 py-1.5 rounded-lg bg-accent text-bg text-sm font-semibold">Add provider</button>
      <span id="providerMsg" class="text-xs ml-3"></span>
    </div>
  </div>
</div>

<script>
"use strict";
/* ------------------------------------------------------------------ state */
const state = {
  tab: "master",
  catalog: null,
  statuses: {},
  buffers: { master: [], m1: [], m2: [], m3: [], m4: [], m5: [], m6: [], m7: [] },
  cursors: { master: 0, m1: 0, m2: 0, m3: 0, m4: 0, m5: 0, m6: 0, m7: 0 },
  overrides: {},   // tab -> {model, mode}
  cards: {},       // tag -> rendered DOM
};
const AGENT_IDS = ["m1","m2","m3","m4","m5","m6","m7"];
const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ helpers */
const STATUS_CLS = { idle: "dot-idle", thinking: "dot-thinking", active: "dot-active", error: "dot-error" };
const STATUS_LBL = { idle: "Idle", thinking: "Planning", active: "Building", error: "Error" };
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function dotCls(tag) { return STATUS_CLS[state.statuses[tag]] || "dot-idle"; }

function statusTitle(tag) {
  const s = state.statuses[tag] || "idle";
  return `${STATUS_LBL[s] || "Idle"} · ${tag.toUpperCase()}`;
}

/* ------------------------------------------------------------------ catalog */
async function loadCatalog() {
  const res = await fetch("/api/catalog");
  state.catalog = await res.json();
  const agentNav = $("agentNav");
  agentNav.innerHTML = "";
  for (const [tag, name, agent] of state.catalog.agents) {
    const b = document.createElement("button");
    b.className = "nav-btn w-10 h-10 rounded-lg flex flex-col items-center justify-center text-muted hover:text-txt hover:bg-panel2 transition group relative";
    b.dataset.tab = tag;
    b.title = `${tag.toUpperCase()} · ${name} (${agent})`;
    b.innerHTML = `<span class="text-sm font-bold">${tag.toUpperCase().replace("M","")}</span><span class="w-1.5 h-1.5 rounded-full mt-0.5 ${dotCls(tag)}" data-dot="${tag}"></span>`;
    agentNav.appendChild(b);
  }
  bindNav();
  // seed overrides with defaults
  for (const tag of ["master", ...AGENT_IDS]) {
    state.overrides[tag] = { model: state.catalog.autoModel, mode: state.catalog.autoMode };
  }
  renderHeader();
}

/* ------------------------------------------------------------------ nav */
function bindNav() {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const t = btn.dataset.tab;
      if (t === "settings") { $("settings").classList.remove("hidden"); loadProviders(); return; }
      selectTab(t);
    });
  });
}

function selectTab(tag) {
  state.tab = tag;
  document.querySelectorAll(".nav-btn").forEach(b => {
    const active = b.dataset.tab === tag;
    b.classList.toggle("bg-panel2", active);
    b.classList.toggle("text-txt", active);
  });
  $("lblTab").textContent = tag === "master" ? "Master Console" : tag.toUpperCase();
  renderHeader();
  renderChat();
  renderCanvas();
}

/* ------------------------------------------------------------------ header */
function renderHeader() {
  const selModel = $("selModel"), selMode = $("selMode");
  const ov = state.overrides[state.tab] || {};
  const models = state.catalog.models, modesByModel = state.catalog.modesByModel;

  selModel.innerHTML = "";
  for (const m of models) {
    const o = document.createElement("option");
    o.value = m; o.textContent = m;
    o.selected = (m === ov.model);
    selModel.appendChild(o);
  }
  selModel.value = ov.model || models[0];
  refreshModes(selModel.value);
  if (ov.mode) selMode.value = ov.mode;

  $("tabDot").className = "dot " + dotCls(state.tab);
  $("tabDot").title = statusTitle(state.tab);
}

function refreshModes(model) {
  const selMode = $("selMode");
  const list = state.catalog.modesByModel[model] || state.catalog.defaultModes || [];
  selMode.innerHTML = "";
  for (const m of list) {
    const o = document.createElement("option");
    o.value = m; o.textContent = m;
    selMode.appendChild(o);
  }
  if (list.length && !selMode.value) selMode.value = list[0];
}

$("selModel").addEventListener("change", () => {
  const model = $("selModel").value;
  state.overrides[state.tab] = state.overrides[state.tab] || {};
  state.overrides[state.tab].model = model;
  refreshModes(model);
  state.overrides[state.tab].mode = $("selMode").value;
  $("tabDot").className = "dot " + dotCls(state.tab);
});
$("selMode").addEventListener("change", () => {
  state.overrides[state.tab] = state.overrides[state.tab] || {};
  state.overrides[state.tab].mode = $("selMode").value;
});

/* ------------------------------------------------------------------ chat */
function chatCard(tag) {
  const card = document.createElement("div");
  card.className = "card p-4";
  card.dataset.tag = tag;
  const isMaster = tag === "master";
  const title = isMaster ? "Master Console" : tag.toUpperCase();
  const meta = isMaster ? "aggregated swarm output" : (state.catalog.agents.find(a => a[0] === tag) || [])[1] || tag;
  card.innerHTML = `
    <div class="flex items-center gap-2 mb-2">
      <span class="dot ${dotCls(tag)}" data-dot="${tag}"></span>
      <span class="font-semibold text-sm">${esc(title)}</span>
      <span class="text-xs text-muted">${esc(meta)}</span>
      <span class="flex-1"></span>
      <span class="text-[10px] font-mono text-muted">${esc(state.overrides[tag]?.model || "")} / ${esc(state.overrides[tag]?.mode || "")}</span>
    </div>
    <div class="acc" data-acc>
      <div class="acc-head flex items-center gap-2 px-3 py-2 bg-panel2/50">
        <span class="text-xs text-muted transition-transform">▸</span>
        <span class="text-xs font-semibold text-muted">Thoughts &amp; process</span>
        <span class="flex-1"></span>
        <span class="text-[10px] text-muted" data-count>0 lines</span>
      </div>
      <div class="acc-body"><pre class="px-3 py-2 font-mono text-[11px] text-muted leading-relaxed whitespace-pre-wrap"></pre></div>
    </div>
    <div class="mt-2 border border-edge rounded-lg bg-bg p-3">
      <div class="text-[10px] uppercase tracking-wider text-muted mb-1">Response</div>
      <pre class="resp font-mono text-xs text-txt whitespace-pre-wrap leading-relaxed">${isMaster ? "" : "— idle —"}</pre>
    </div>`;
  card.querySelector(".acc-head").addEventListener("click", () => {
    const acc = card.querySelector("[data-acc]");
    acc.classList.toggle("open");
    card.querySelector(".acc-head span").textContent = acc.classList.contains("open") ? "▾" : "▸";
  });
  return card;
}

function renderChat() {
  const chat = $("chat");
  chat.innerHTML = "";
  if (state.tab === "master") {
    const card = chatCard("master");
    chat.appendChild(card);
    state.cards["master"] = card;
  } else {
    const card = chatCard(state.tab);
    chat.appendChild(card);
    state.cards[state.tab] = card;
    // replay buffer
    for (const line of state.buffers[state.tab] || []) appendToCard(state.tab, "line", line);
  }
}

function appendToCard(tag, kind, text) {
  if (state.tab !== tag && tag !== "master") return; // only live tab + master? master renders below
  // ensure card exists (run creates cards for all, but if tab differs we skip)
  const card = state.cards[tag];
  if (!card || (state.tab !== tag)) return;
  const accBody = card.querySelector(".acc-body pre");
  const count = card.querySelector("[data-count]");
  const resp = card.querySelector(".resp");
  const el = document.createElement("div");
  el.textContent = text;
  accBody.appendChild(el);
  const n = accBody.childElementCount;
  count.textContent = n + " lines";
  if (kind !== "line") {
    const r = document.createElement("div");
    r.textContent = text;
    r.className = kind === "error" ? "text-danger" : "";
    resp.appendChild(r);
  }
  accBody.parentElement.scrollTop = accBody.parentElement.scrollHeight;
}

/* ------------------------------------------------------------------ console */
function renderCanvas() {
  const tag = state.tab === "master" ? "master" : state.tab;
  $("canvasTag").textContent = tag;
  const out = $("canvasOut");
  out.innerHTML = "";
  const lines = state.buffers[tag] || [];
  if (!lines.length) {
    const d = document.createElement("div");
    d.className = "text-muted";
    d.textContent = "— no output yet —";
    out.appendChild(d);
    return;
  }
  // Stream everything linearly: plain lines as terminal text, fenced code
  // blocks rendered inline as highlighted blocks (keeps previews readable).
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      const lang = fence[1];
      const block = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        block.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // skip closing fence
      const pre = document.createElement("pre");
      pre.className = "codeblock";
      const c = document.createElement("code");
      if (lang) c.className = "language-" + lang;
      c.textContent = block.join("\n");
      pre.appendChild(c);
      out.appendChild(pre);
      try { hljs.highlightElement(c); } catch (_) {}
    } else {
      const d = document.createElement("div");
      d.textContent = line;
      out.appendChild(d);
      i++;
    }
  }
  out.scrollTop = out.scrollHeight;
}

/* ------------------------------------------------------------------ run */
async function runCommand(prompt) {
  if (!prompt.trim()) return;
  $("input").value = "";
  autosize();
  const payload = { prompt, overrides: {} };
  for (const tag of ["master", ...AGENT_IDS]) {
    payload.overrides[tag] = { ...state.overrides[tag] };
  }
  await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  // user message card
  const chat = $("chat");
  const user = document.createElement("div");
  user.className = "card p-3 flex items-start gap-3";
  user.innerHTML = `<div class="shrink-0 w-8 h-8 rounded-lg bg-accent/20 text-accent flex items-center justify-center font-bold">U</div>
    <div class="text-sm text-txt whitespace-pre-wrap">${esc(prompt)}</div>`;
  chat.insertBefore(user, chat.firstChild);
}

async function onClickRun() {
  const prompt = $("input").value;
  await runCommand(prompt);
}

/* ------------------------------------------------------------------ input */
function autosize() {
  const ta = $("input");
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 240) + "px";
}
$("input").addEventListener("input", autosize);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onClickRun(); }
});
document.querySelectorAll(".pill").forEach(p => {
  p.classList.add("px-3","py-1","rounded-full","border","border-edge","text-xs","text-muted","hover:text-txt","hover:border-accent","transition");
  p.addEventListener("click", () => {
    $("input").value = p.dataset.pill;
    autosize(); $("input").focus();
  });
});

/* ------------------------------------------------------------------ SSE */
function connectStream() {
  const es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") {
      state.statuses = msg.statuses;
      for (const tag in msg.history) state.buffers[tag] = msg.history[tag];
      syncDots();
      if (state.tab !== "master") renderChat();
      renderCanvas();
    } else if (msg.type === "delta") {
      for (const e of msg.events || []) {
        if (e.kind === "status") { state.statuses[e.tag] = e.text; }
        else if (e.kind === "line" || e.kind === "error") {
          (state.buffers[e.tag] = state.buffers[e.tag] || []).push(e.text);
        }
      }
      syncDots();
      if (state.tab !== "master") renderChat();
      renderCanvas();
    }
  };
  es.onerror = () => { /* EventSource auto-reconnects */ };
}

function syncDots() {
  document.querySelectorAll("[data-dot]").forEach(el => {
    const tag = el.dataset.dot;
    el.className = "dot " + dotCls(tag);
    el.parentElement.title = statusTitle(tag);
  });
  $("tabDot").className = "dot " + dotCls(state.tab);
  $("tabDot").title = statusTitle(state.tab);
  for (const tag in state.cards) {
    const card = state.cards[tag];
    const d = card.querySelector("[data-dot]");
    if (d) d.className = "dot " + dotCls(tag);
  }
}

/* ------------------------------------------------------------------ controls */
$("btnSidebar").addEventListener("click", () => {
  const sb = $("sidebar");
  const hidden = sb.style.width === "0px";
  sb.style.width = hidden ? "" : "0px";
});
$("btnClear").addEventListener("click", async () => {
  await fetch("/api/clear", { method: "POST" });
  state.buffers = { master: [], m1: [], m2: [], m3: [], m4: [], m5: [], m6: [], m7: [] };
  renderChat(); renderCanvas();
});
$("btnStop").addEventListener("click", async () => {
  await fetch("/api/terminate", { method: "POST" });
});
$("btnWorkspace").addEventListener("click", () => {
  const p = prompt("Workspace directory:", window.__workspace || "");
  if (p) {
    fetch("/api/workspace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: p }),
    }).then(r => r.json()).then(d => { if (d.workspace) { window.__workspace = d.workspace; $("lblWorkspace").textContent = "workspace: " + d.workspace; } });
  }
});
$("btnRun").addEventListener("click", onClickRun);
$("btnSettingsClose").addEventListener("click", () => $("settings").classList.add("hidden"));

/* ------------------------------------------------------------------ settings / providers */
async function loadProviders() {
  const res = await fetch("/api/providers");
  const list = await res.json();
  const wrap = $("providers");
  wrap.innerHTML = "";
  if (!list.length) {
    wrap.innerHTML = '<div class="text-xs text-muted">No custom providers configured (only built-in opencode models).</div>';
  }
  for (const p of list) {
    const card = document.createElement("div");
    card.className = "border border-edge rounded-lg p-3 mb-3";
    card.innerHTML = `
      <div class="flex items-center gap-2 mb-2">
        <span class="font-mono font-semibold text-sm">${esc(p.name)}</span>
        <span class="text-[10px] text-muted font-mono">${esc(p.npm)}</span>
        <span class="flex-1"></span>
        <button class="px-2 py-0.5 text-xs rounded border border-edge text-muted hover:text-txt" data-del="${esc(p.name)}">delete</button>
      </div>
      <input data-url data-name="${esc(p.name)}" value="${esc(p.baseURL)}" placeholder="base URL" class="w-full text-xs rounded px-2 py-1.5 mb-2">
      <input data-models data-name="${esc(p.name)}" value="${esc(p.models.join(", "))}" placeholder="models, comma separated" class="w-full text-xs rounded px-2 py-1.5 mb-2">
      <button class="px-2 py-0.5 text-xs rounded bg-accent text-bg font-semibold" data-save="${esc(p.name)}">save</button>`;
    wrap.appendChild(card);
  }
  wrap.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm(`Delete provider '${b.dataset.del}'?`)) return;
    await fetch("/api/providers/" + encodeURIComponent(b.dataset.del), { method: "DELETE" });
    loadProviders();
  }));
  wrap.querySelectorAll("[data-save]").forEach(b => b.addEventListener("click", async () => {
    const name = b.dataset.save;
    const card = b.closest(".border");
    const url = card.querySelector("[data-url]").value;
    const models = card.querySelector("[data-models]").value.split(",").map(s => s.trim()).filter(Boolean);
    await fetch("/api/providers/" + encodeURIComponent(name), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseURL: url, models }),
    });
    loadProviders();
  }));
}

$("btnAddProvider").addEventListener("click", async () => {
  const name = $("pName").value.trim();
  const baseURL = $("pURL").value.trim();
  const npm = $("pNpm").value.trim();
  const models = $("pModels").value.split(",").map(s => s.trim()).filter(Boolean);
  if (!name) { $("providerMsg").textContent = "name required"; return; }
  const res = await fetch("/api/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, baseURL, npm, models }),
  });
  $("providerMsg").textContent = res.ok ? "added ✓" : "error: " + (await res.text());
  if (res.ok) {
    $("pName").value = $("pURL").value = $("pNpm").value = $("pModels").value = "";
    loadProviders();
    // refresh catalog dropdowns
    loadCatalog();
  }
});

/* ------------------------------------------------------------------ boot */
(async function boot() {
  await loadCatalog();
  const res = await fetch("/api/status");
  const st = await res.json();
  window.__workspace = st.workspace || "";
  $("lblWorkspace").textContent = "workspace: " + (st.workspace || "…");
  selectTab("master");
  connectStream();
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- entry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MultiAgentCoding Web UI (Dyad-style)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the default web browser")
    parser.add_argument("--workspace", default=str(PROJECT_ROOT), help="initial workspace directory")
    args = parser.parse_args(argv)

    HUB.workspace = Path(args.workspace).expanduser().resolve()
    url = f"http://{args.host}:{args.port}"
    print(f"MultiAgentCoding Web UI -> {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

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
import time
import urllib.error
import urllib.request
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
    prune_prompt,
)

# Self-evolution engine (pure stdlib; no web_app dependency).
from self_evolve import Proposal, SelfEvolveEngine, detect_optimization_loops

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


def _options_env_var(options: dict) -> str | None:
    """Extract the env var name from an ``{env:VAR}`` apiKey reference."""
    api_key = options.get("apiKey", "")
    if isinstance(api_key, str) and api_key.startswith("{env:") and api_key.endswith("}"):
        return api_key[len("{env:"):-1]
    return None


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
        """Spawn one worker thread per agent (mirrors desktop RUN COMMAND).

        The original prompt stays in the master buffer; agents receive the
        pruned copy, and the pruned prompt is recorded in state.md.
        """
        if not prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt must not be empty.")
        self.append_line("master", f"▶ {prompt}")
        pruned = prune_prompt(prompt)
        STATE.record_run(pruned, time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.lock:
            self.running += len(AGENTS)
        for tag, name, agent in AGENTS:
            model, mode = self.resolve(tag, overrides)
            self.set_status(tag, STATUS_THINKING)
            threading.Thread(
                target=self._run_agent,
                args=(tag, name, agent, pruned, model, mode),
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
        ok = False
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
                ok = True
                self.set_status(tag, STATUS_IDLE)
        except Exception as exc:  # noqa: BLE001 — surface in UI
            self.append_error(tag, f"[{tag} {name}] ERROR: {exc}")
            self.set_status(tag, STATUS_ERROR)
        finally:
            with self.lock:
                self.running = max(0, self.running - 1)
            STATE.record_finish(tag, ok)

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
        STATE.record_restart("interrupted", "terminated by user")


HUB = WebHub()

# --------------------------------------------------------------------------- state tracker


def _state_escape(text: str) -> str:
    """Escape backslashes/newlines for a single-line state.md field."""
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _state_unescape(text: str) -> str:
    """Invert _state_escape (only ``\\n`` and ``\\\\`` are escaped)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt == "n" else nxt)
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


class StateTracker:
    """Read/write the workspace ``state.md`` checkpoint (sections format).

    Sections: ``## Phase``, ``## Last Run``, ``## Completed``, ``## Active
    Worktrees``, ``## Decisions``, ``## Pending Modification``, ``## Restart
    Log``. Writes mirror ``_write_config`` (temp file + ``os.replace``) so a
    crash never leaves a half-written state file. Never touches ``knowledge/``
    or writes API keys/secrets.
    """

    MAX_COMPLETED = 20

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else PROJECT_ROOT / "state.md"
        self.lock = threading.Lock()

    def load(self) -> dict | None:
        """Parse state.md into a dict, or None when missing/corrupt."""
        if not self.path.exists():
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        return self._parse(text)

    def update(self, **fields: object) -> dict:
        """Merge ``fields`` into the on-disk state and write atomically."""
        return self._mutate(lambda data: data.update(fields))

    def record_run(self, prompt: str, started: str) -> dict:
        return self.update(
            phase="running",
            last_run={"prompt": prompt, "started": started},
        )

    def record_finish(self, tag: str, ok: bool) -> dict:
        return self._mutate(
            lambda data: data.setdefault("completed", []).append(
                f"{tag}: {'ok' if ok else 'failed'}"
            )
        )

    def record_decision(self, text: str) -> dict:
        return self._mutate(lambda data: data.setdefault("decisions", []).append(text))

    def record_pending_modification(self, detail: str) -> dict:
        return self.update(pending_modification=detail)

    def clear_pending_modification(self) -> dict:
        return self.update(pending_modification=None)

    def record_restart(self, action: str, result: str) -> dict:
        return self._mutate(
            lambda data: data.setdefault("restart_log", []).append(f"{action}: {result}")
        )

    # ------------------------------------------------------------ internals

    def _mutate(self, transform) -> dict:
        with self.lock:
            data = self.load() or {}
            transform(data)
            data = self._compress(data)
            self._write(data)
            return data

    def _compress(self, data: dict) -> dict:
        """Trim ``## Completed`` beyond MAX_COMPLETED into a summary line."""
        completed = list(data.get("completed") or [])
        if len(completed) > self.MAX_COMPLETED:
            excess = len(completed) - self.MAX_COMPLETED
            data["completed"] = [f"… {excess} earlier finishes compressed"] + completed[-self.MAX_COMPLETED:]
        return data

    def _parse(self, text: str) -> dict | None:
        """Split ``## Section`` blocks; None when no sections are present."""
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current = stripped[3:].strip()
                sections[current] = []
            elif current is not None:
                sections[current].append(line)
        if not sections:
            return None

        phase_lines = sections.get("Phase") or []
        phase = phase_lines[0].strip() if phase_lines and phase_lines[0].strip() else "idle"

        last_run = None
        run_lines = sections.get("Last Run") or []
        if run_lines:
            prompt = ""
            started = ""
            for line in run_lines:
                if line.startswith("prompt:"):
                    prompt = _state_unescape(line[len("prompt:"):].strip())
                elif line.startswith("started:"):
                    started = line[len("started:"):].strip()
            last_run = {"prompt": prompt, "started": started}

        def bullets(name: str) -> list[str]:
            out = []
            for line in sections.get(name) or []:
                item = line.strip().lstrip("-").strip()
                if item:
                    out.append(item)
            return out

        pending = "\n".join(sections.get("Pending Modification") or []).strip()

        return {
            "phase": phase,
            "last_run": last_run,
            "completed": bullets("Completed"),
            "active_worktrees": bullets("Active Worktrees"),
            "decisions": bullets("Decisions"),
            "pending_modification": pending or None,
            "restart_log": bullets("Restart Log"),
        }

    def _render(self, data: dict) -> str:
        lines = ["# State", ""]
        lines += ["## Phase", str(data.get("phase") or "idle"), ""]
        last_run = data.get("last_run")
        if last_run:
            lines += [
                "## Last Run",
                f"prompt: {_state_escape(str(last_run.get('prompt', '')))}",
                f"started: {str(last_run.get('started', ''))}",
                "",
            ]
        for key, heading in (
            ("completed", "Completed"),
            ("active_worktrees", "Active Worktrees"),
            ("decisions", "Decisions"),
        ):
            lines += [f"## {heading}"]
            lines += [f"- {entry}" for entry in (data.get(key) or [])]
            lines.append("")
        lines += ["## Pending Modification"]
        pending = data.get("pending_modification")
        if pending:
            lines.append(str(pending))
        lines.append("")
        lines += ["## Restart Log"]
        lines += [f"- {entry}" for entry in (data.get("restart_log") or [])]
        lines.append("")
        return "\n".join(lines)

    def _write(self, data: dict) -> None:
        """Atomic write via temp file + replace (mirrors _write_config)."""
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".state.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self._render(data))
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


STATE = StateTracker()

# --------------------------------------------------------------------------- self-evolve engine

# Gatekeeper for self-modification flows. record_decision resolves STATE at
# call time so tests that swap web_app.STATE keep working.
SELF_EVOLVE_ENGINE = SelfEvolveEngine(
    project_root=PROJECT_ROOT,
    record_decision=lambda text: STATE.record_decision(text),
)

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


def _apply_limits(models_block: dict, limits: dict | None) -> None:
    """Write ``limit: {context, output}`` under each model that has one."""
    if not limits:
        return
    for model_id, limit in limits.items():
        if model_id in models_block and isinstance(limit, dict):
            models_block[model_id]["limit"] = limit


def list_providers() -> list[dict]:
    config = _load_config()
    providers = config.get("provider", {})
    result = []
    for name, block in providers.items():
        options = block.get("options", {})
        env_var = _options_env_var(options)
        status = provider_status(name, env_var, options.get("baseURL"))
        models_block = block.get("models", {})
        limits = {
            model_id: model["limit"]
            for model_id, model in models_block.items()
            if isinstance(model, dict) and isinstance(model.get("limit"), dict)
        }
        result.append(
            {
                "name": name,
                "npm": block.get("npm", ""),
                "baseURL": options.get("baseURL", ""),
                "models": sorted(models_block.keys()),
                "status": status["status"],
                "statusSource": status["source"],
                "envVar": status["envVar"],
                "isBuiltin": _builtin_provider(name) is not None,
                "limits": limits,
            }
        )
    return result


def add_provider(
    name: str,
    npm: str,
    base_url: str,
    models: list[str],
    env_var: str | None = None,
    limits: dict[str, dict[str, int]] | None = None,
) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Provider name must not be empty.")
    config = _load_config()
    if name in config.get("provider", {}):
        raise HTTPException(status_code=409, detail=f"Provider '{name}' already exists.")
    options: dict = {"baseURL": base_url} if base_url else {}
    if env_var:
        options["apiKey"] = f"{{env:{env_var}}}"
    models_block = {m: {"name": m} for m in models if m.strip()}
    _apply_limits(models_block, limits)
    config.setdefault("provider", {})[name] = {
        "npm": npm or "@ai-sdk/openai-compatible",
        "name": name,
        "options": options,
        "models": models_block,
    }
    _write_config(config)
    return {"ok": True, "name": name}


def update_provider(
    name: str,
    npm: str | None,
    base_url: str | None,
    models: list[str] | None,
    env_var: str | None = None,
    limits: dict[str, dict[str, int]] | None = None,
) -> dict:
    config = _load_config()
    providers = config.setdefault("provider", {})
    if name not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")
    block = providers[name]
    if npm is not None:
        block["npm"] = npm or "@ai-sdk/openai-compatible"
    if base_url is not None:
        block.setdefault("options", {})["baseURL"] = base_url
    if env_var is not None:
        options = block.setdefault("options", {})
        if env_var.strip():
            options["apiKey"] = f"{{env:{env_var.strip()}}}"
        else:
            options.pop("apiKey", None)
    if models is not None:
        block["models"] = {m: {"name": m} for m in models if m.strip()}
    if limits is not None:
        _apply_limits(block.setdefault("models", {}), limits)
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


def provider_matrix() -> list[dict]:
    """Merge built-ins, detected auth.json keys, and custom providers.

    Built-in rows get their status from auth/env; custom provider rows (from
    opencode.json) override built-in defaults when names collide.
    """
    rows: dict[str, dict] = {}
    for provider in BUILTIN_PROVIDERS:
        name = provider["id"]
        status = provider_status(name, None, provider["baseURL"])
        rows[name] = {
            "name": name,
            "npm": provider["npm"],
            "baseURL": provider["baseURL"],
            "models": [],
            "status": status["status"],
            "statusSource": status["source"],
            "envVar": status["envVar"],
            "isBuiltin": True,
            "limits": {},
        }
    for name in _auth_store():
        if name in rows:
            continue
        status = provider_status(name)
        rows[name] = {
            "name": name,
            "npm": "",
            "baseURL": "",
            "models": [],
            "status": status["status"],
            "statusSource": status["source"],
            "envVar": status["envVar"],
            "isBuiltin": False,
            "limits": {},
        }
    for row in list_providers():
        name = row["name"]
        if name in rows:
            merged = dict(row)
            merged["isBuiltin"] = rows[name]["isBuiltin"]
            if not merged.get("npm"):
                merged["npm"] = rows[name]["npm"]
            if not merged.get("baseURL"):
                merged["baseURL"] = rows[name]["baseURL"]
            rows[name] = merged
        else:
            rows[name] = row
    return list(rows.values())


def _extract_model_ids(payload: dict) -> list[str]:
    """Pull model IDs from an OpenAI-compatible ``/models`` response.

    Accepts ``{"data": [{"id": ...}]}`` (OpenAI style) or ``{"models": [...]}``
    where entries are strings or ``{"id": ...}`` dicts. Unknown shapes -> [].
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("data")
    if raw is None:
        raw = payload.get("models")
    if not isinstance(raw, list):
        return []
    ids = []
    for entry in raw:
        if isinstance(entry, str) and entry:
            ids.append(entry)
        elif isinstance(entry, dict) and entry.get("id"):
            ids.append(entry["id"])
    return ids


def discover_models(base_url: str, api_key: str | None) -> dict:
    """Query ``GET {base_url}/models`` with a Bearer key (6s timeout).

    Returns ``{ok, models, status, error}``. ``status`` is ``ok`` or a typed
    error: invalid_key (401/403), not_compatible (404/405), rate_limited
    (429), unreachable (timeout/connection). The key is only used in-memory
    for the request; it is never persisted or logged.
    """
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "models": [], "status": "invalid_key", "error": f"Invalid API key (HTTP {exc.code})."}
        if exc.code in (404, 405):
            return {"ok": False, "models": [], "status": "not_compatible", "error": f"Endpoint not found (HTTP {exc.code}) — provider may not be OpenAI-compatible."}
        if exc.code == 429:
            return {"ok": False, "models": [], "status": "rate_limited", "error": "Rate limited (HTTP 429)."}
        return {"ok": False, "models": [], "status": "error", "error": f"HTTP {exc.code}."}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "models": [], "status": "unreachable", "error": f"Provider unreachable: {exc}"}
    return {"ok": True, "models": _extract_model_ids(payload), "status": "ok", "error": None}


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
    envVar: str | None = None
    limits: dict[str, dict[str, int]] = Field(default_factory=dict)


class ProviderPatch(BaseModel):
    npm: str | None = None
    baseURL: str | None = None
    models: list[str] | None = None
    envVar: str | None = None
    limits: dict[str, dict[str, int]] | None = None


class VerifyRequest(BaseModel):
    providerName: str
    baseURL: str
    envVar: str | None = None
    apiKey: str | None = None  # in-memory only; never persisted or echoed


class ImportModelsRequest(BaseModel):
    models: list[str] = Field(default_factory=list)


class WorkspaceIn(BaseModel):
    path: str


class SelfEvolveRequest(BaseModel):
    prompt: str = ""
    mode: str = "explicit"  # explicit | detect
    overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class ApproveProposalRequest(BaseModel):
    overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class RestartRequest(BaseModel):
    reason: str = "restart requested"


# --------------------------------------------------------------------------- app

app = FastAPI(title="MultiAgentCoding Web UI", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE_HTML


@app.get("/api/status")
def api_status() -> dict:
    return {"statuses": HUB.statuses, "running": HUB.running, "workspace": str(HUB.workspace)}


@app.get("/api/state")
def api_state() -> dict:
    """Return the current state.md checkpoint (None when missing/corrupt)."""
    return {"checkpoint": STATE.load()}


@app.post("/api/state/refresh")
def api_state_refresh() -> dict:
    """Re-read state.md from disk and return the fresh checkpoint."""
    return {"checkpoint": STATE.load()}


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


# --------------------------------------------------------------------------- self-evolve endpoints


def _proposal_to_dict(proposal: Proposal) -> dict:
    return {
        "id": proposal.id,
        "agent": proposal.agent,
        "signature": proposal.signature,
        "count": proposal.count,
        "suggestion": proposal.suggestion,
    }


def _after_self_evolve_run(prompt: str, overrides: dict) -> None:
    """Wait for the dispatched swarm run, then verify and write the restart marker.

    Runs on a daemon thread so the endpoint never blocks the SSE/run loop.
    On verification failure the restart is recorded in state.md and no
    marker is written (the supervisor must not relaunch on a bad build).
    """
    while HUB.running > 0:
        time.sleep(0.2)
    result = SELF_EVOLVE_ENGINE.verify()
    if result["ok"]:
        SELF_EVOLVE_ENGINE.write_restart_marker(
            payload={
                "source": "self-evolve",
                "prompt": prompt,
                "ok": True,
                "verified": True,
            }
        )
    else:
        STATE.record_restart("verify", "failed: " + "; ".join(result.get("errors") or []))


def _spawn_self_evolve_watcher(prompt: str, overrides: dict) -> None:
    """Start the verify+marker watcher on a daemon thread (patchable in tests)."""
    threading.Thread(
        target=_after_self_evolve_run,
        args=(prompt, overrides),
        name="self-evolve-watcher",
        daemon=True,
    ).start()


def _dispatch_self_evolve(prompt: str, overrides: dict, label: str) -> None:
    """Append a master log line, dispatch the swarm, and schedule verify+marker."""
    HUB.append_line("master", f"▶ self-evolve ({label}): {prompt}")
    HUB.run(prompt, overrides)
    _spawn_self_evolve_watcher(prompt, overrides)


@app.post("/api/self-evolve")
def api_self_evolve(req: SelfEvolveRequest) -> dict:
    """Self-modification endpoint.

    ``mode=explicit`` records a checkpoint decision, dispatches the swarm,
    then (on a watcher thread) verifies the repo and writes the restart
    marker on success. ``mode=detect`` only returns optimization-loop
    proposals — it never dispatches.
    """
    if req.mode == "detect":
        return {
            "ok": True,
            "mode": "detect",
            "proposals": [_proposal_to_dict(p) for p in detect_optimization_loops()],
        }
    if req.mode != "explicit":
        raise HTTPException(status_code=400, detail="mode must be 'explicit' or 'detect'")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")
    checkpoint = SELF_EVOLVE_ENGINE.checkpoint(req.prompt)
    _dispatch_self_evolve(req.prompt, req.overrides, "explicit")
    return {"ok": True, "mode": "explicit", "checkpoint": checkpoint}


@app.get("/api/optimization-proposals")
def api_optimization_proposals() -> dict:
    """Return detected optimization-loop proposals (detection never dispatches)."""
    return {
        "ok": True,
        "proposals": [_proposal_to_dict(p) for p in detect_optimization_loops()],
    }


@app.post("/api/optimization-proposals/{proposal_id}/approve")
def api_optimization_proposals_approve(proposal_id: str, req: ApproveProposalRequest) -> dict:
    """Approve one proposal: record the decision in state.md and dispatch the
    swarm with the proposal's suggestion as the prompt."""
    proposal = next(
        (p for p in detect_optimization_loops() if p.id == proposal_id), None
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found.")
    decision = f"approved optimization proposal {proposal.id}: {proposal.suggestion}"
    STATE.record_decision(decision)
    _dispatch_self_evolve(proposal.suggestion, req.overrides, f"approved {proposal.id}")
    return {"ok": True, "approved": proposal.id, "decision": decision}


def _schedule_exit(delay: float = 1.0) -> None:
    """Schedule ``os._exit(0)`` on a short timer (patchable in tests).

    The delay lets the 202 response reach the client before the process dies;
    the supervisor then reads the restart marker and relaunches.
    """
    threading.Timer(delay, lambda: os._exit(0)).start()


@app.post("/api/restart", status_code=202)
def api_restart(req: RestartRequest) -> dict:
    """Request a supervised restart: record it, write the marker, then exit.

    Records ``STATE.record_restart(reason, "requested")``, writes the restart
    marker the supervisor watches, returns 202, and schedules ``os._exit(0)``
    on a short timer so the response is delivered before the supervisor acts.
    """
    STATE.record_restart(req.reason, "requested")
    SELF_EVOLVE_ENGINE.write_restart_marker(
        payload={"source": "api-restart", "reason": req.reason, "ok": True}
    )
    _schedule_exit()
    return {"ok": True, "reason": req.reason, "restart": "scheduled"}


@app.post("/api/workspace")
def api_workspace(req: WorkspaceIn) -> dict:
    p = Path(req.path).expanduser().resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {p}")
    HUB.workspace = p
    return {"ok": True, "workspace": str(p)}


@app.get("/api/providers")
def api_providers() -> list[dict]:
    return provider_matrix()


@app.post("/api/providers", status_code=201)
def api_providers_add(body: ProviderIn) -> dict:
    return add_provider(body.name, body.npm, body.baseURL, body.models, body.envVar, body.limits)


@app.put("/api/providers/{name}")
def api_providers_update(name: str, body: ProviderPatch) -> dict:
    return update_provider(name, body.npm, body.baseURL, body.models, body.envVar, body.limits)


@app.delete("/api/providers/{name}")
def api_providers_delete(name: str) -> dict:
    return delete_provider(name)


@app.post("/api/providers/verify")
def api_providers_verify(body: VerifyRequest) -> dict:
    """Resolve a key (env/auth or the in-memory one) and discover models.

    The key is used only for the request; it is never persisted or echoed.
    """
    key, _ = resolve_api_key(body.providerName, body.envVar)
    if not key:
        key = body.apiKey
    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No API key for provider '{body.providerName}'. "
                f"Set {body.envVar or 'an env var'} or pass a key to verify."
            ),
        )
    return discover_models(body.baseURL, key)


@app.post("/api/providers/{name}/import-models")
def api_providers_import_models(name: str, body: ImportModelsRequest) -> dict:
    """Add discovered model IDs to the provider block with default names."""
    config = _load_config()
    providers = config.setdefault("provider", {})
    if name not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found.")
    models = providers[name].setdefault("models", {})
    imported = 0
    for model_id in body.models:
        model_id = model_id.strip()
        if not model_id or model_id in models:
            continue
        models[model_id] = {"name": model_id}
        imported += 1
    _write_config(config)
    return {"ok": True, "name": name, "imported": imported, "models": sorted(models.keys())}


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
  /* ---- typography scale: base 16px, small = 13px+ (no more 9-11px) ---- */
  html { font-size: 16px; }
  html, body { height: 100%; }
  body { font-size: 15px; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb { background: #2c3a52; border-radius: 6px; }
  ::-webkit-scrollbar-thumb:hover { background: #384a66; }
  ::-webkit-scrollbar-track { background: transparent; }
  .card { background: #0F172A; border: 1px solid #293548; border-radius: 14px; box-shadow: 0 8px 28px rgba(0,0,0,0.28); }
  .dot { width: 10px; height: 10px; border-radius: 9999px; display: inline-block; }
  .dot-idle { background: #64748B; }
  .dot-thinking { background: #38BDF8; animation: pulse 1s infinite; box-shadow: 0 0 10px rgba(56,189,248,0.7); }
  .dot-active { background: #A3E635; animation: pulse 1s infinite; box-shadow: 0 0 10px rgba(163,230,53,0.7); }
  .dot-error { background: #F87171; box-shadow: 0 0 8px rgba(248,113,113,0.6); }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
  .acc { border: 1px solid #293548; border-radius: 12px; overflow: hidden; }
  .acc-head { cursor: pointer; user-select: none; }
  .acc-body { max-height: 0; overflow: hidden; transition: max-height 0.25s ease; }
  .acc.open .acc-body { max-height: 560px; overflow: auto; }
  select, textarea, input:not([type="checkbox"]) { background: #0B0E14; border: 1px solid #293548; color: #E2E8F0; }
  select:focus, textarea:focus { outline: none; border-color: #38BDF8; box-shadow: 0 0 0 3px rgba(56,189,248,0.15); }
  /* API & Models Manager modal inputs: dark grey fields, crisp text, muted placeholders */
  #settings input:not([type="checkbox"]) {
    background: #1E293B;
    border: 1px solid #334155;
    color: #F8FAFC;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 13px;
  }
  #settings input::placeholder { color: #94A3B8; }
  #settings input:focus { outline: none; border-color: #38BDF8; box-shadow: 0 0 0 3px rgba(56,189,248,0.15); }
  /* provider matrix status badges + source chips */
  .badge-ready { background: rgba(74, 222, 128, 0.16); color: #4ADE80; border: 1px solid rgba(74, 222, 128, 0.45); }
  .badge-needs-setup { background: rgba(251, 191, 36, 0.16); color: #FBBF24; border: 1px solid rgba(251, 191, 36, 0.45); }
  .badge-local { background: rgba(148, 163, 184, 0.16); color: #94A3B8; border: 1px solid rgba(148, 163, 184, 0.45); }
  .chip-auth { background: rgba(56, 189, 248, 0.16); color: #38BDF8; }
  .chip-env { background: rgba(167, 139, 250, 0.16); color: #A78BFA; }
  .chip-none { background: rgba(148, 163, 184, 0.16); color: #94A3B8; }
  pre.codeblock { font-family: "JetBrains Mono", monospace; font-size: 13px; line-height: 1.7; }
  /* --- polished interactive primitives --- */
  .btn { transition: all 0.15s ease; }
  .btn:hover { transform: translateY(-1px); }
  .nav-btn.active { background: #1E293B; color: #E2E8F0; box-shadow: inset 0 0 0 1px #38BDF8; }
  .pill { transition: all 0.15s ease; }
  .pill:hover { transform: translateY(-1px); border-color: #38BDF8; color: #E2E8F0; }
  .console-tab { transition: all 0.15s ease; }
  .console-tab.active { background: #1E293B; color: #38BDF8; border-color: #38BDF8; }
  /* single-window: stack the terminal console under the chat on narrow screens */
  @media (max-width: 900px) {
    #console { width: 100% !important; border-left: none !important; border-top: 1px solid #293548; }
  }
</style>
</head>
<body class="bg-bg text-txt font-sans h-screen overflow-hidden flex flex-col">

<!-- top bar -->
<div class="flex items-center gap-3 px-4 py-2.5 border-b border-edge bg-panel">
  <button id="btnSidebar" class="btn text-muted text-xl leading-none w-9 h-9 rounded-lg hover:bg-panel2 transition" title="Toggle sidebar">☰</button>
  <div class="flex-1 text-sm text-muted truncate min-w-0">
    <span class="text-txt font-semibold text-[15px]">MultiAgentCoding</span>
    <span class="mx-2 text-edge">|</span>
    <span id="lblWorkspace" class="font-mono text-[13px]">workspace: …</span>
  </div>
  <button id="btnWorkspace" class="btn text-[13px] px-3 py-1.5 rounded-lg border border-edge text-muted hover:text-txt hover:border-accent transition">Change…</button>
  <button id="btnClear" class="btn text-[13px] px-3 py-1.5 rounded-lg border border-edge text-muted hover:text-txt transition">Clear</button>
  <button id="btnStop" class="btn text-[13px] px-3 py-1.5 rounded-lg border border-edge text-danger hover:text-txt transition">Stop</button>
</div>

<div class="flex flex-1 min-h-0">

  <!-- left icon sidebar -->
  <aside id="sidebar" class="w-14 shrink-0 border-r border-edge bg-panel flex flex-col items-center py-3 gap-1.5 transition-all duration-200 overflow-hidden">
    <button data-tab="master" class="nav-btn w-11 h-11 rounded-xl text-lg text-muted hover:text-txt hover:bg-panel2 transition flex items-center justify-center" title="Master Console">⌂</button>
    <div class="w-8 border-t border-edge my-1"></div>
    <div id="agentNav" class="flex flex-col items-center gap-1.5"></div>
    <div class="flex-1"></div>
    <div class="w-8 border-t border-edge my-1"></div>
    <button data-tab="settings" class="nav-btn w-11 h-11 rounded-xl text-lg text-muted hover:text-txt hover:bg-panel2 transition flex items-center justify-center" title="API & Models">⚙</button>
  </aside>

  <!-- center workplane -->
  <main class="flex-1 flex flex-col min-w-0">

    <!-- tab header: cascading model/mode dropdowns + status dot -->
    <div class="flex items-center gap-3 px-4 py-2.5 border-b border-edge bg-panel flex-wrap">
      <span id="lblTab" class="font-semibold text-[15px]">Master Console</span>
      <span id="tabDot" class="dot dot-idle"></span>
      <div class="flex-1"></div>
      <label class="text-[13px] text-muted">Model</label>
      <select id="selModel" class="text-[13px] rounded-lg px-2.5 py-2 w-64"></select>
      <label class="text-[13px] text-muted ml-2">Mode</label>
      <select id="selMode" class="text-[13px] rounded-lg px-2.5 py-2 w-48"></select>
    </div>

    <!-- chat + streaming console: one unified column (no dead zones) -->
    <div class="flex flex-1 min-h-0">
      <!-- chat messages -->
      <div id="chat" class="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-w-0"></div>

      <!-- streaming terminal console, docked inside the main workplane -->
      <div id="console" class="w-[24rem] shrink-0 border-l border-edge bg-panel flex flex-col min-w-0">
        <div class="px-3 py-2 border-b border-edge flex items-center gap-2 flex-wrap">
          <span class="text-[13px] font-semibold text-muted">Terminal Logs</span>
          <span id="canvasTag" class="font-mono text-accent text-[13px]">m1</span>
          <div class="flex-1"></div>
          <div id="consoleTabs" class="flex items-center gap-1"></div>
        </div>
        <div id="canvasOut" class="flex-1 min-h-0 m-2 overflow-auto rounded-lg bg-bg border border-edge p-2.5 font-mono text-[13px] text-txt leading-relaxed"></div>
      </div>
    </div>

    <!-- quick action pills + input -->
    <div class="border-t border-edge bg-panel px-4 pt-2.5 pb-3">
      <div class="flex items-center gap-2 flex-wrap mb-2" id="quickActions">
        <span class="text-[13px] text-muted">Quick actions:</span>
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
  <div class="card w-full max-w-4xl max-h-[85vh] overflow-auto p-5">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">⚙ API &amp; Models Manager</h2>
      <button id="btnSettingsClose" class="text-muted hover:text-txt text-xl leading-none">✕</button>
    </div>
    <p class="text-xs text-muted mb-4">Manages the <code class="font-mono">provider</code> block of <code class="font-mono">opencode.json</code>.
      API keys are never stored here — they live in <code class="font-mono">~/.local/share/opencode/auth.json</code>.</p>

    <!-- provider matrix grid -->
    <div id="providerMatrix" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"></div>

    <!-- provider detail view (hidden) -->
    <div id="providerDetail" class="hidden"></div>

    <!-- add custom provider onboarding form (hidden) -->
    <div id="addProviderForm" class="hidden">
      <div class="border-t border-edge mt-4 pt-4">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold">Add custom provider</h3>
          <button id="btnCancelAdd" class="px-2 py-0.5 text-xs rounded border border-edge text-muted hover:text-txt">← Back</button>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <input id="pName" placeholder="name (e.g. openrouter)" class="text-xs rounded px-2 py-1.5">
          <input id="pURL" placeholder="base URL (optional)" class="text-xs rounded px-2 py-1.5">
          <input id="pEnvVar" placeholder="env var for API key (optional)" class="text-xs rounded px-2 py-1.5">
          <input id="pNpm" placeholder="adapter (default @ai-sdk/openai-compatible)" class="text-xs rounded px-2 py-1.5">
          <input id="pModels" placeholder="models, comma separated (e.g. openrouter/auto, deepseek/deepseek-chat)" class="text-xs rounded px-2 py-1.5 col-span-2">
        </div>
        <button id="btnAddProvider" class="mt-3 px-4 py-1.5 rounded-lg bg-accent text-bg text-sm font-semibold">Add provider</button>
        <span id="providerMsg" class="text-xs ml-3"></span>
      </div>
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
  checkpoint: null, // state.md checkpoint from /api/state (resume card)
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
  if (state.tab === "master" && state.checkpoint) chat.appendChild(resumeCard());
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

/* ------------------------------------------------------------------ resume */
function resumeSummaryText() {
  const ck = state.checkpoint || {};
  const lines = [];
  lines.push("Continue the previous workflow from the last checkpoint.");
  lines.push("");
  lines.push(`Phase: ${ck.phase || "idle"}`);
  const completed = ck.completed || [];
  lines.push(`Completed: ${completed.length} finish record(s)`);
  const worktrees = ck.active_worktrees || [];
  if (worktrees.length) lines.push(`Active worktrees: ${worktrees.join(", ")}`);
  if (ck.pending_modification) {
    lines.push(`Pending modification: ${ck.pending_modification}`);
  }
  const decisions = ck.decisions || [];
  if (decisions.length) {
    lines.push("Decisions:");
    for (const d of decisions.slice(0, 5)) lines.push(`- ${d}`);
    if (decisions.length > 5) lines.push(`- … ${decisions.length - 5} more`);
  }
  lines.push("");
  lines.push("Resume the workflow where it left off.");
  return lines.join("\n");
}

function resumeCard() {
  const card = document.createElement("div");
  card.className = "card p-4";
  card.id = "resumeCard";
  const ck = state.checkpoint || {};
  const completed = (ck.completed || []).length;
  const decisions = (ck.decisions || []).length;
  const pending = ck.pending_modification;
  card.innerHTML = `
    <div class="flex items-center gap-2 mb-2">
      <span class="w-2 h-2 rounded-full bg-lime"></span>
      <span class="font-semibold text-sm">Resume from checkpoint?</span>
      <span class="flex-1"></span>
      <span class="text-[10px] font-mono text-muted">state.md</span>
    </div>
    <div class="text-xs text-muted mb-3 space-y-1">
      <div>Phase: <span class="text-txt font-mono">${esc(ck.phase || "idle")}</span></div>
      <div>Completed: <span class="text-txt font-mono">${completed}</span> record(s)</div>
      ${pending ? `<div>Pending modification: <span class="text-lime font-mono">${esc(String(pending).slice(0, 200))}</span></div>` : ""}
      <div>Decisions: <span class="text-txt font-mono">${decisions}</span> note(s)</div>
    </div>
    <div class="flex items-center gap-2">
      <button id="btnResume" class="px-3 py-1.5 rounded-lg bg-lime text-bg text-xs font-semibold">Resume</button>
      <button id="btnDismiss" class="px-3 py-1.5 rounded border border-edge text-xs text-muted hover:text-txt">Dismiss</button>
      <span class="text-[10px] text-muted">Loads the checkpoint summary into the prompt; nothing runs automatically.</span>
    </div>`;
  card.querySelector("#btnResume").addEventListener("click", () => {
    const ta = $("input");
    ta.value = resumeSummaryText();
    autosize();
    ta.focus();
  });
  card.querySelector("#btnDismiss").addEventListener("click", () => {
    state.checkpoint = null;
    card.remove();
  });
  return card;
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
const STATUS_BADGE = {
  ready: { label: "Ready", cls: "badge-ready" },
  "needs-setup": { label: "Needs Setup", cls: "badge-needs-setup" },
  local: { label: "Local", cls: "badge-local" },
};
const SOURCE_CHIP = {
  auth: "chip-auth",
  env: "chip-env",
  none: "chip-none",
};

function statusBadge(status) {
  const b = STATUS_BADGE[status] || STATUS_BADGE["needs-setup"];
  return `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold ${b.cls}">${b.label}</span>`;
}

function sourceChip(source) {
  return `<span class="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase ${SOURCE_CHIP[source] || SOURCE_CHIP.none}">${esc(source || "none")}</span>`;
}

function providerTile(p) {
  const tile = document.createElement("div");
  tile.className = "border border-edge rounded-lg p-3 cursor-pointer hover:border-accent transition";
  tile.dataset.provider = p.name;
  tile.innerHTML = `
    <div class="flex items-center gap-2 mb-2">
      <span class="font-mono font-semibold text-sm">${esc(p.name)}</span>
      <span class="flex-1"></span>
      ${statusBadge(p.status)}
    </div>
    <div class="text-[10px] text-muted font-mono mb-2">${esc(p.npm || "—")}</div>
    <div class="flex items-center gap-2">
      ${sourceChip(p.statusSource)}
      <span class="text-[10px] text-muted truncate">${esc(p.baseURL || "no base URL")}</span>
    </div>`;
  tile.addEventListener("click", () => openProviderDetail(p));
  return tile;
}

function addProviderTile() {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "border-2 border-dashed border-edge rounded-lg p-3 text-muted hover:text-accent hover:border-accent transition flex flex-col items-center justify-center gap-1";
  tile.innerHTML = `<span class="text-2xl leading-none">+</span><span class="text-xs font-semibold">Add custom provider</span>`;
  tile.addEventListener("click", () => openAddProviderForm());
  return tile;
}

async function loadProviders() {
  const res = await fetch("/api/providers");
  const list = await res.json();
  const wrap = $("providerMatrix");
  wrap.innerHTML = "";
  for (const p of list) wrap.appendChild(providerTile(p));
  wrap.appendChild(addProviderTile());
}

const VERIFY_ERROR_LBL = {
  invalid_key: "Invalid API key",
  not_compatible: "Not OpenAI-compatible",
  rate_limited: "Rate limited",
  unreachable: "Provider unreachable",
  error: "Error",
};

function verifyErrorChip(status, error) {
  const lbl = VERIFY_ERROR_LBL[status] || "Error";
  return `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold badge-needs-setup">${lbl}</span> <span class="text-xs text-muted">${esc(error || "")}</span>`;
}

function modelLimitRow(m, lim) {
  lim = lim || {};
  const row = document.createElement("div");
  row.className = "flex items-center gap-2 mb-1";
  row.dataset.model = m;
  row.innerHTML = `
    <span class="font-mono text-xs flex-1 truncate" title="${esc(m)}">${esc(m)}</span>
    <input data-ctx value="${lim.context || ""}" placeholder="—" title="Context Window" class="w-24 text-right rounded px-1 py-1 text-xs">
    <input data-out value="${lim.output || ""}" placeholder="—" title="Max Output Tokens" class="w-24 text-right rounded px-1 py-1 text-xs">
    <button data-rm class="text-muted hover:text-danger text-xs w-6" title="remove">✕</button>`;
  row.querySelector("[data-rm]").addEventListener("click", () => row.remove());
  return row;
}

function renderModelLimits(models, limits) {
  const wrap = $("modelLimits");
  wrap.innerHTML = "";
  const header = document.createElement("div");
  header.className = "flex items-center gap-2 mb-1 text-[10px] text-muted uppercase tracking-wider";
  header.innerHTML = `<span class="flex-1">Model</span><span class="w-24 text-right">Context Window</span><span class="w-24 text-right">Max Output Tokens</span><span class="w-6"></span>`;
  wrap.appendChild(header);
  if (!models.length) {
    const empty = document.createElement("div");
    empty.className = "text-xs text-muted mb-1";
    empty.textContent = "No models yet — verify & discover, or add one below.";
    wrap.appendChild(empty);
  }
  for (const m of models) wrap.appendChild(modelLimitRow(m, (limits || {})[m]));
  const addRow = document.createElement("div");
  addRow.className = "flex items-center gap-2";
  addRow.innerHTML = `<input id="newModel" placeholder="add model id" class="flex-1 text-xs rounded px-2 py-1.5"><button id="btnAddModel" class="px-2 py-1 rounded border border-edge text-xs text-muted hover:text-txt">add</button>`;
  wrap.appendChild(addRow);
  $("btnAddModel").addEventListener("click", () => {
    const v = $("newModel").value.trim();
    if (!v) return;
    $("newModel").value = "";
    wrap.insertBefore(modelLimitRow(v, {}), addRow);
  });
}

function openProviderDetail(p) {
  $("providerMatrix").classList.add("hidden");
  $("addProviderForm").classList.add("hidden");
  const detail = $("providerDetail");
  detail.classList.remove("hidden");
  detail.innerHTML = `
    <div class="border-t border-edge mt-4 pt-4">
      <div class="flex items-center gap-2 mb-2">
        <button id="btnBackDetail" class="px-2 py-0.5 text-xs rounded border border-edge text-muted hover:text-txt">← Back</button>
        <span class="font-mono font-semibold text-sm">${esc(p.name)}</span>
        ${statusBadge(p.status)}
        ${sourceChip(p.statusSource)}
        <span class="flex-1"></span>
        <button class="px-2 py-0.5 text-xs rounded border border-edge text-muted hover:text-txt" data-del="${esc(p.name)}">delete</button>
      </div>
      <div class="text-[10px] text-muted font-mono mb-2">${esc(p.npm || "—")}</div>
      <input data-url value="${esc(p.baseURL)}" placeholder="base URL" class="w-full text-xs rounded px-2 py-1.5 mb-2">
      <div class="grid grid-cols-2 gap-2 mb-2">
        <input data-envvar value="${esc(p.envVar || "")}" placeholder="env var for API key (optional)" class="text-xs rounded px-2 py-1.5">
        <input data-apikey type="password" placeholder="API key (verify only, never saved)" class="text-xs rounded px-2 py-1.5">
      </div>
      <div class="flex items-center gap-2 mb-2">
        <button id="btnVerify" class="px-3 py-1.5 rounded-lg bg-accent text-bg text-xs font-semibold">Verify &amp; discover</button>
        <span id="verifySpinner" class="hidden text-xs text-muted">checking…</span>
      </div>
      <div id="verifyResult" class="mb-2"></div>
      <div id="discoveredModels" class="hidden mb-2"></div>
      <div id="modelLimits" class="mb-2"></div>
      <div class="flex items-center gap-2">
        <button id="btnSaveDetail" class="px-3 py-1.5 rounded-lg bg-accent text-bg text-xs font-semibold">save</button>
        <span id="detailMsg" class="text-xs ml-1"></span>
      </div>
    </div>`;
  renderModelLimits(p.models || [], p.limits || {});

  detail.querySelector("[data-del]").addEventListener("click", async () => {
    if (!confirm(`Delete provider '${p.name}'?`)) return;
    await fetch("/api/providers/" + encodeURIComponent(p.name), { method: "DELETE" });
    closeProviderDetail();
    loadProviders();
  });

  $("btnVerify").addEventListener("click", async () => {
    const btn = $("btnVerify");
    const spinner = $("verifySpinner");
    const result = $("verifyResult");
    const discovered = $("discoveredModels");
    btn.disabled = true;
    spinner.classList.remove("hidden");
    result.innerHTML = "";
    discovered.classList.add("hidden");
    discovered.innerHTML = "";
    const body = {
      providerName: p.name,
      baseURL: detail.querySelector("[data-url]").value.trim(),
      envVar: detail.querySelector("[data-envvar]").value.trim() || null,
      apiKey: detail.querySelector("[data-apikey]").value || null,
    };
    try {
      const res = await fetch("/api/providers/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        result.innerHTML = `<span class="text-xs text-danger">${esc(data.detail || "verify failed")}</span>`;
      } else if (data.ok) {
        renderDiscovered(data.models, result);
      } else {
        result.innerHTML = verifyErrorChip(data.status, data.error);
      }
    } catch (err) {
      result.innerHTML = `<span class="text-xs text-danger">verify error: ${esc(String(err))}</span>`;
    } finally {
      btn.disabled = false;
      spinner.classList.add("hidden");
    }
  });

  function renderDiscovered(models, result) {
    const wrap = $("discoveredModels");
    wrap.classList.remove("hidden");
    wrap.innerHTML = "";
    result.innerHTML = `<span class="text-xs text-lime">Connected — ${models.length} model(s) found</span>`;
    if (!models.length) return;
    const title = document.createElement("div");
    title.className = "text-xs text-muted mb-1";
    title.textContent = "Discovered models (select to import):";
    wrap.appendChild(title);
    const importBtn = document.createElement("button");
    importBtn.id = "btnImportModels";
    importBtn.className = "mt-2 px-3 py-1 rounded-lg bg-accent text-bg text-xs font-semibold";
    importBtn.textContent = "Import models";
    importBtn.disabled = true;
    for (const m of models) {
      const label = document.createElement("label");
      label.className = "flex items-center gap-2 text-xs py-0.5 cursor-pointer";
      label.innerHTML = `<input type="checkbox" data-disc="${esc(m)}" class="accent-accent"> <span class="font-mono">${esc(m)}</span>`;
      label.querySelector("input").addEventListener("change", () => {
        const n = wrap.querySelectorAll("input[type=checkbox]:checked").length;
        importBtn.textContent = n ? `Import ${n} models` : "Import models";
        importBtn.disabled = !n;
      });
      wrap.appendChild(label);
    }
    importBtn.addEventListener("click", async () => {
      const checked = [...wrap.querySelectorAll("input[type=checkbox]:checked")].map(c => c.dataset.disc);
      if (!checked.length) return;
      if (!confirm(`Import ${checked.length} model(s) into '${p.name}'?`)) return;
      const res = await fetch("/api/providers/" + encodeURIComponent(p.name) + "/import-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ models: checked }),
      });
      const data = await res.json();
      if (!res.ok) {
        result.innerHTML = `<span class="text-xs text-danger">${esc(data.detail || "import failed")}</span>`;
        return;
      }
      result.innerHTML = `<span class="text-xs text-lime">Imported ${data.imported} model(s)</span>`;
      refreshProviderDetail(p.name);
    });
    wrap.appendChild(importBtn);
  }

  $("btnSaveDetail").addEventListener("click", async () => {
    const url = detail.querySelector("[data-url]").value.trim();
    const envVar = detail.querySelector("[data-envvar]").value.trim();
    const models = [];
    const limits = {};
    $("modelLimits").querySelectorAll("[data-model]").forEach(row => {
      const m = row.dataset.model;
      if (!m || models.includes(m)) return;
      models.push(m);
      const lim = {};
      const ctx = parseInt(row.querySelector("[data-ctx]").value, 10);
      const out = parseInt(row.querySelector("[data-out]").value, 10);
      if (ctx) lim.context = ctx;
      if (out) lim.output = out;
      if (Object.keys(lim).length) limits[m] = lim;
    });
    const res = await fetch("/api/providers/" + encodeURIComponent(p.name), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseURL: url, envVar, models, limits }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      $("detailMsg").textContent = "error: " + (data.detail || res.status);
      return;
    }
    closeProviderDetail();
    loadProviders();
    loadCatalog();
  });

  detail.querySelector("#btnBackDetail").addEventListener("click", () => {
    closeProviderDetail();
    loadProviders();
  });
}

async function refreshProviderDetail(name) {
  const res = await fetch("/api/providers");
  const list = await res.json();
  const p = list.find(x => x.name === name);
  if (p) openProviderDetail(p);
}

function closeProviderDetail() {
  $("providerDetail").classList.add("hidden");
  $("providerMatrix").classList.remove("hidden");
}

function openAddProviderForm() {
  $("providerMatrix").classList.add("hidden");
  $("providerDetail").classList.add("hidden");
  $("addProviderForm").classList.remove("hidden");
}

$("btnCancelAdd").addEventListener("click", () => {
  $("addProviderForm").classList.add("hidden");
  $("providerMatrix").classList.remove("hidden");
});

$("btnAddProvider").addEventListener("click", async () => {
  const name = $("pName").value.trim();
  const baseURL = $("pURL").value.trim();
  const envVar = $("pEnvVar").value.trim();
  const npm = $("pNpm").value.trim();
  const models = $("pModels").value.split(",").map(s => s.trim()).filter(Boolean);
  if (!name) { $("providerMsg").textContent = "name required"; return; }
  const res = await fetch("/api/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, baseURL, envVar, npm, models }),
  });
  $("providerMsg").textContent = res.ok ? "added ✓" : "error: " + (await res.text());
  if (res.ok) {
    $("pName").value = $("pURL").value = $("pEnvVar").value = $("pNpm").value = $("pModels").value = "";
    $("addProviderForm").classList.add("hidden");
    $("providerMatrix").classList.remove("hidden");
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
  try {
    const sres = await fetch("/api/state");
    const sdata = await sres.json();
    state.checkpoint = sdata.checkpoint || null;
  } catch (_) { state.checkpoint = null; }
  selectTab("master");
  connectStream();
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- window launcher

_EDGE_CANDIDATES = [
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
]


def _find_edge() -> str | None:
    for cand in _EDGE_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    return None


def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def _launch_window(url: str) -> bool:
    """Open a standalone window; block until closed. Returns True if a window was shown."""
    try:
        import webview  # type: ignore
        webview.create_window("MultiAgentCoding", url)
        webview.start()
        return True
    except Exception:
        pass
    edge = _find_edge()
    if edge:
        subprocess.run([edge, "--app", url], check=False)
        return True
    webbrowser.open(url)
    return True


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

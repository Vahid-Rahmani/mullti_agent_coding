"""API routes for the web dashboard — thin layer over the existing backend.

No backend capability is reinvented here. Every handler either:
  * reads existing state (``HUB`` / ``VaultBridge`` / ``ContextResolver`` /
    the node graph), or
  * performs a write through an existing safe primitive (``VaultBridge`` /
    ``update_task``), or
  * shells out to the real Orchestrator CLI so locks, backups, transitions
    and Agent-Report parsing stay in the existing pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from scripts.core import opencode_cfg, orchestrator as orch
from scripts.core.agents import (
    AGENTS, AGENT_SPEC_BY_AGENT, AGENT_SPEC_BY_TAG, PROJECT_ROOT,
)
from scripts.core.context_resolver import resolve_context
from scripts.core.run_hub import HUB
from scripts.web_ui import settings as ui_settings
from scripts.core.vault_bridge import (
    VALID_STATUSES,
    VaultError,
    _now,
    is_dispatchable,
    list_tasks,
    read_task,
    resolve_task,
    update_task,
)
from scripts.web_ui import graph as vgraph
from scripts.web_ui.state import WebState

_REPO_ROOT = PROJECT_ROOT
AGENT_TAGS = [tag for tag, _name, _agent in AGENTS]
AGENT_TAG_TO_AGENT = {tag: agent for tag, _name, agent in AGENTS}
AGENT_TO_NAME = {spec.agent: spec.name for spec in AGENT_SPEC_BY_AGENT.values()}


# ---------------------------------------------------------------- request models


class DispatchIn(BaseModel):
    prompt: str
    agent: Optional[str] = None  # tag like "m4"; None → all agents


class AssignIn(BaseModel):
    agent: str  # opencode agent key, e.g. "matthew"


class StatusIn(BaseModel):
    status: str


class SettingsTestIn(BaseModel):
    provider: str
    key: Optional[str] = None
    base_url: Optional[str] = None
    auth: Optional[str] = None


class SettingsDiscoverIn(BaseModel):
    provider: str
    key: Optional[str] = None
    base_url: Optional[str] = None
    auth: Optional[str] = None


class SettingsSaveIn(BaseModel):
    provider: str
    mode: str = "simple"
    key: Optional[str] = None
    base_url: Optional[str] = None
    auth: Optional[str] = None
    models: Optional[list[str]] = None


class SettingsManualModelIn(BaseModel):
    model: str


class SettingsModelIn(BaseModel):
    agent: str
    model: str


class SettingsFallbackIn(BaseModel):
    fallback_models: list[str]


class SettingsModeIn(BaseModel):
    mode: str
    description: Optional[str] = None


# ---------------------------------------------------------------- helpers


def _task_path(state_vault: Path, name: str) -> Path:
    """Task node path with safe 404s; raises HTTPException on bad nodes.

    The name is resolved through ``resolve_task`` so traversal, absolute-path,
    and separator inputs can never escape ``03-Tasks/``. Unsafe names are
    rejected with the same 404 as a missing node (no filesystem detail leaks).
    """
    path = resolve_task(state_vault, name)
    if path is None or not path.is_file():
        raise HTTPException(404, f"task not found: {name}")
    try:
        read_task(path)
    except VaultError as exc:
        raise HTTPException(422, str(exc)) from exc
    return path


def _tail(path: Path, max_lines: int) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    return [line.rstrip("\r\n") for line in lines[-max_lines:]]


def _open_task_proc(state_vault: Path, name: str) -> subprocess.Popen:
    argv = [
        sys.executable, "-m", "scripts.core.orchestrator",
        "--vault", str(state_vault), "dispatch", name, "--yes",
    ]
    return subprocess.Popen(
        argv,
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


# ---------------------------------------------------------------- router factory


def create_router(state_vault: Path, state: WebState) -> APIRouter:
    router = APIRouter()

    # ---- live state -------------------------------------------------------

    @router.get("/api/state")
    async def api_state() -> dict:
        snap = state.snapshot()
        snap["prefs"] = state.prefs
        return snap

    @router.get("/api/agents")
    async def api_agents() -> dict:
        snap = state.snapshot()
        agents = []
        for tag, name, agent in AGENTS:
            spec = AGENT_SPEC_BY_TAG.get(tag)
            # Persisted spec file is authoritative (in-memory spec.model is a
            # frozen import-time snapshot); keeps dashboard == Settings model.
            model = None
            if spec is not None:
                model = opencode_cfg.read_spec_model(spec.agent) or spec.model
            agents.append({
                "tag": tag,
                "name": name,
                "agent": agent,
                "model": model,
                "status": snap["statuses"].get(tag, "idle"),
                "progress": snap["progress"].get(tag, 0),
                "token_usage": snap["token_usage"].get(tag, 0),
                "running": tag in snap["session_tags"],
                "prompt": snap["prompts"].get(tag, ""),
            })
        return {"agents": agents, "prefs": state.prefs}

    @router.get("/api/sessions")
    async def api_sessions() -> dict:
        return {"sessions": state.sessions()}

    @router.get("/api/events")
    async def api_events(since: int = 0) -> dict:
        events = state.drain()
        return {"events": events, "n": state.snapshot()["n"]}

    @router.get("/api/events/stream")
    async def api_events_stream():
        async def generate():
            while True:
                events = state.drain()
                for e in events:
                    yield f"event: {e['kind']}\ndata: {json.dumps(e)}\n\n"
                if not events:
                    yield ": ping\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- dispatch ---------------------------------------------------------

    @router.post("/api/dispatch")
    async def api_dispatch(body: DispatchIn) -> dict:
        prompt = (body.prompt or "").strip()
        if not prompt:
            raise HTTPException(400, "prompt must not be empty")
        tag = body.agent
        if tag is not None and tag not in AGENT_TAGS:
            raise HTTPException(404, f"unknown agent {tag!r}")
        error = HUB.run(prompt, agents=[tag] if tag is not None else None)
        if error:
            raise HTTPException(409, error)
        state.push_usermsg(tag or "master", f"▶ dispatched (target={tag or 'all'})")
        return {"ok": True, "agents": [tag] if tag is not None else AGENT_TAGS}

    @router.post("/api/stop/{tag}")
    async def api_stop_agent(tag: str) -> dict:
        if tag not in AGENT_TAGS:
            raise HTTPException(404, f"unknown agent {tag!r}")
        HUB.terminate_agent(tag)
        return {"ok": True}

    @router.post("/api/stop")
    async def api_stop_all() -> dict:
        HUB.terminate_all()
        return {"ok": True}

    # ---- vault / graph ----------------------------------------------------

    @router.get("/api/vault/graph")
    async def api_graph(refresh: bool = False) -> dict:
        graph = vgraph.get_graph(state_vault, refresh=refresh)
        return {"nodes": graph["nodes"], "edges": graph["edges"], "vault": str(state_vault)}

    @router.get("/api/vault/node/{name}")
    async def api_node(name: str) -> dict:
        path = vgraph.find_node(state_vault, name)
        if path is None:
            raise HTTPException(404, f"node not found: {name}")
        raw = path.read_text(encoding="utf-8", errors="replace")
        m = vgraph.FRONTMATTER_RE.match(raw)
        fields: dict[str, str] = {}
        frontmatter_error = None
        if m:
            fields, frontmatter_error = vgraph.parse_frontmatter(raw)
        else:
            frontmatter_error = "missing frontmatter block (file must start with ---)"
        body = raw[m.end():] if m else raw
        return {
            "name": name,
            "path": str(path.relative_to(state_vault)).replace(os.sep, "/"),
            "folder": "root" if path.parent == state_vault else path.parent.name,
            "fields": fields,
            "body": body,
            "frontmatter_error": frontmatter_error,
        }

    @router.get("/api/vault/node/{name}/related")
    async def api_node_related(name: str) -> dict:
        try:
            rel = vgraph.node_relationships(state_vault, name)
        except VaultError as exc:
            raise HTTPException(404, str(exc)) from exc
        return rel

    @router.get("/api/vault/context/{name}")
    async def api_context(name: str) -> dict:
        path = vgraph.find_node(state_vault, name)
        if path is None:
            raise HTTPException(404, f"node not found: {name}")
        try:
            package = resolve_context(state_vault, path)
        except VaultError as exc:
            raise HTTPException(422, str(exc)) from exc
        return package.to_dict()

    # ---- tasks ------------------------------------------------------------

    @router.get("/api/tasks")
    async def api_tasks() -> dict:
        tasks = []
        for path in list_tasks(state_vault):
            try:
                fields, _body, _raw = read_task(path)
            except VaultError:
                continue
            tasks.append({
                "name": path.stem,
                "status": fields.get("status", ""),
                "priority": fields.get("priority", ""),
                "assigned_agent": fields.get("assigned_agent", ""),
                "updated": fields.get("updated", ""),
            })
        tasks.sort(key=lambda t: (t["status"], t["name"]))
        return {"tasks": tasks}

    @router.post("/api/tasks/{name}/assign")
    async def api_task_assign(name: str, body: AssignIn) -> dict:
        spec = AGENT_SPEC_BY_AGENT.get(body.agent)
        if spec is None:
            raise HTTPException(404, f"unknown agent key {body.agent!r}")
        path = _task_path(state_vault, name)
        new_fields = update_task(
            path, "web-ui-assign",
            {"assigned_agent": f"Agent_{spec.name}", "status": "ready",
             "updated": _now()[:10]},
        )
        return {
            "name": name,
            "assigned_agent": new_fields.get("assigned_agent", ""),
            "status": new_fields.get("status", ""),
        }

    @router.post("/api/tasks/{name}/status")
    async def api_task_status(name: str, body: StatusIn) -> dict:
        if body.status not in VALID_STATUSES:
            allowed = ", ".join(sorted(VALID_STATUSES))
            raise HTTPException(400, f"invalid status {body.status!r}; allowed: {allowed}")
        path = _task_path(state_vault, name)
        fields, _body, _raw = read_task(path)
        try:
            orch._transition(name, fields, body.status)
        except VaultError as exc:
            raise HTTPException(409, str(exc)) from exc
        new_fields = update_task(
            path, "set-status", {"status": body.status, "updated": _now()[:10]},
        )
        return {"name": name, "status": new_fields.get("status", "")}

    @router.post("/api/tasks/{name}/dispatch")
    async def api_task_dispatch(name: str) -> dict:
        path = _task_path(state_vault, name)
        fields, _body, _raw = read_task(path)
        if fields.get("status") != "ready":
            raise HTTPException(
                409, f"{name}: status must be 'ready' to dispatch (got {fields.get('status')})")
        ok_dispatch, why = is_dispatchable(fields)
        if not ok_dispatch:
            raise HTTPException(409, f"{name}: cannot dispatch — {why}")
        if state.task_running(name):
            raise HTTPException(409, f"{name}: already executing (another run in flight)")

        proc = _open_task_proc(state_vault, name)
        state.register_task_proc(name, proc)
        state.push_task_run(name, f"▶ orchestrator dispatch {name} (pid {proc.pid})")

        def pump() -> None:
            try:
                line = "x"  # sentinel for first iteration below
                assert proc.stdout is not None
                for raw in proc.stdout:
                    text = raw.rstrip("\r\n")
                    if text:
                        state.push_task_line(name, text)
            except Exception as exc:  # noqa: BLE001
                state.push_task_line(name, f"(stream error: {exc})")
            finally:
                returncode = proc.wait()
                state.pop_task_proc(name)
                state.push_task_done(name, f"── dispatch finished ({returncode}) ──")

        threading.Thread(target=pump, name=f"task-{name}", daemon=True).start()
        return {"ok": True, "name": name, "running": True}

    @router.post("/api/tasks/{name}/cancel")
    async def api_task_cancel(name: str) -> dict:
        proc = state.pop_task_proc(name)
        if proc is None:
            raise HTTPException(404, f"{name}: not currently running")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc.terminate()
        state.push_task_line(name, "── cancelled by operator ──")
        return {"ok": True}

    # ---- logs -------------------------------------------------------------

    @router.get("/api/logs/orchestrator")
    async def api_log_orchestrator(max_lines: int = Query(default=200, ge=1, le=5000)) -> dict:
        return {"lines": _tail(_REPO_ROOT / "_logs" / "orchestrator.log", max_lines)}

    @router.get("/api/logs/{agent}")
    async def api_log_agent(agent: str, max_lines: int = Query(default=200, ge=1, le=5000)) -> dict:
        key = agent.lower()
        path = _REPO_ROOT / "_logs" / f"{key}.log"
        lines = _tail(path, max_lines)
        if not path.is_file():
            raise HTTPException(404, f"no log for {key!r} yet (the launcher writes it)")
        return {"agent": key, "lines": lines}

    # ---- settings (Phase 25 / 25A) ----------------------------------------

    def _settings_known(provider_id: str) -> bool:
        return ui_settings.provider_known(provider_id)

    def _set_conn_status(provider_id: str, status: str) -> None:
        """Persist a tested/validation_failed status across reloads."""
        current = dict(state.prefs.get("conn_status") or {})
        current[provider_id] = status
        state.update_prefs({"conn_status": current})

    @router.get("/api/settings")
    async def api_settings() -> dict:
        return {
            "vault": str(state_vault),
            "sections": ["general", "connections", "models", "agents",
                         "modes", "graph", "security"],
            "simple_providers": [
                {"id": p["id"], "name": p["name"]} for p in ui_settings.SIMPLE_PROVIDERS
            ],
        }

    @router.get("/api/settings/connections")
    async def api_settings_connections() -> dict:
        return {"providers": ui_settings.connections(
            status_overrides=state.prefs.get("conn_status") or {})}

    @router.post("/api/settings/connections/test")
    async def api_settings_test(body: SettingsTestIn) -> dict:
        if not _settings_known(body.provider):
            raise HTTPException(404, f"unknown provider {body.provider!r}")
        try:
            result = ui_settings.test_connection(
                body.provider, key=body.key, base_url=body.base_url, auth=body.auth)
        except opencode_cfg.ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc
        _set_conn_status(body.provider,
                         "tested" if result.get("ok") else "validation_failed")
        return result

    @router.post("/api/settings/connections/discover")
    async def api_settings_discover(body: SettingsDiscoverIn) -> dict:
        if not _settings_known(body.provider):
            raise HTTPException(404, f"unknown provider {body.provider!r}")
        return ui_settings.discover_models(
            body.provider, key=body.key, base_url=body.base_url, auth=body.auth)

    @router.post("/api/settings/connections/save")
    async def api_settings_save(body: SettingsSaveIn) -> dict:
        if not _settings_known(body.provider):
            raise HTTPException(404, f"unknown provider {body.provider!r}")
        try:
            result = ui_settings.save_connection(
                body.provider, mode=body.mode, key=body.key, base_url=body.base_url,
                auth=body.auth, models=body.models)
        except opencode_cfg.ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc
        if result.get("configured"):
            _set_conn_status(body.provider, "tested")
        return result

    @router.delete("/api/settings/connections/{provider}")
    async def api_settings_remove(provider: str) -> dict:
        cfg = opencode_cfg.load_config()
        removed = opencode_cfg.remove_provider(cfg, provider)
        if removed:
            opencode_cfg.save_config(cfg)
        ui_settings.remove_api_key(provider)
        return {"ok": True, "removed": removed}

    @router.post("/api/settings/connections/{provider}/models")
    async def api_settings_manual_model(provider: str, body: SettingsManualModelIn) -> dict:
        # Known Simple providers rebuild their canonical block; Advanced
        # providers keep theirs. A polluted block can never be resurrected.
        try:
            return ui_settings.add_manual_model(provider, body.model)
        except opencode_cfg.ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/settings/models/catalog")
    async def api_settings_models_catalog() -> dict:
        """Model catalog fed by saved connections (discovery with stored keys)."""
        return ui_settings.model_catalog()

    @router.get("/api/settings/models")
    async def api_settings_models() -> dict:
        return {"agents": ui_settings.agent_config(),
                "available": ui_settings.available_models()}

    @router.post("/api/settings/models")
    async def api_settings_set_model(body: SettingsModelIn) -> dict:
        try:
            result = ui_settings.apply_model(body.agent, body.model)
        except opencode_cfg.ConfigError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, **result}

    @router.post("/api/settings/agents/{agent}/fallback")
    async def api_settings_fallback(agent: str, body: SettingsFallbackIn) -> dict:
        try:
            result = ui_settings.apply_fallback(agent, body.fallback_models)
        except opencode_cfg.ConfigError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, **result}

    @router.post("/api/settings/agents/{agent}/mode")
    async def api_settings_mode(agent: str, body: SettingsModeIn) -> dict:
        try:
            result = ui_settings.apply_mode(agent, body.mode, description=body.description)
        except opencode_cfg.ConfigError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, **result}

    @router.delete("/api/settings/security/keys/{provider}")
    async def api_settings_remove_key(provider: str) -> dict:
        removed = ui_settings.remove_api_key(provider)
        return {"ok": True, "configured": not removed}

    # ---- preferences ------------------------------------------------------

    @router.get("/api/prefs")
    async def api_get_prefs() -> dict:
        return dict(state.prefs)

    @router.post("/api/prefs")
    async def api_set_prefs(body: dict) -> dict:
        return state.update_prefs(body)

    return router


__all__ = ["create_router", "HUB"]
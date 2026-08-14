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

from scripts.core import opencode_cfg, orchestrator as orch, roles
from scripts.core import model_connections
from scripts.core import model_registry
from scripts.core import prompt_library
from scripts.core import workflow_engine, workflows
from scripts.core.agents import (
    AGENTS, AGENT_SPEC_BY_AGENT, AGENT_SPEC_BY_TAG, PROJECT_ROOT,
)
from scripts.core.context_resolver import resolve_context
from scripts.core.project_profile import (
    analyze_repository,
    suggest_roles,
    suggested_role_reasons,
)
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


class ActiveWorkflowIn(BaseModel):
    workflow_id: str  # persisted workflow id, e.g. "my-pipeline"


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


class RoleCreateIn(BaseModel):
    id: str
    name: Optional[str] = None
    description: str = ""
    responsibilities: list[str] = []
    tools: list[str] = []
    permissions: list[str] = []
    rules: list[str] = []
    expected_outputs: list[str] = []


class RolesAssignIn(BaseModel):
    role_ids: list[str]


class TaskRoleIn(BaseModel):
    role: Optional[str] = None  # role id to override, or empty/None to clear


class WorkflowIn(BaseModel):
    id: str
    name: str = ""
    project: str = ""
    nodes: list[dict] = []
    edges: list[dict] = []
    entry: list[str] = []
    state: dict = {}
    settings: dict = {}


class WorkflowRunIn(BaseModel):
    initial_state: dict = {}


class PromptRecommendIn(BaseModel):
    task: Optional[str] = None
    role: Optional[str] = None
    capabilities: list[str] = []
    complexity: Optional[str] = None
    risk: Optional[str] = None


class ModelRecommendIn(BaseModel):
    task: Optional[str] = None
    prompt_id: Optional[str] = None            # Phase 2 field (kept for compat)
    prompt_profile: Optional[str] = None      # Phase 3 alias
    provider: Optional[str] = None
    explicit_model: Optional[str] = None
    hard_requirements: Optional[dict] = None
    available_models: Optional[list[dict]] = None


class ConnectionCreateIn(BaseModel):
    provider: str
    connection_id: Optional[str] = None
    display_name: Optional[str] = None
    api_key: Optional[str] = None             # accepted ONCE at create; never echoed
    credential_type: str = "api_key"
    endpoint: Optional[str] = None
    deployment: Optional[str] = None
    default: bool = False


class ConnectionUpdateIn(BaseModel):
    display_name: Optional[str] = None
    api_key: Optional[str] = None             # optional replace; never echoed
    credential_type: Optional[str] = None
    endpoint: Optional[str] = None
    deployment: Optional[str] = None
    default: Optional[bool] = None
    status: Optional[str] = None


class ConnectionResolveIn(BaseModel):
    model: Optional[str] = None
    connection_id: Optional[str] = None


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
            # The runtime model is resolved from opencode.json (single source
            # of truth), keeping dashboard == Settings model.
            model = opencode_cfg.resolve_model(spec.agent) if spec is not None else None
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

    # ---- active workflow (single source of truth for Home) ---------------

    @router.get("/api/active-workflow")
    async def api_active_workflow() -> dict:
        """The workflow Home renders and the Home runtime executes.

        Returns ``workflow: null`` when no workflow is active (Home then falls
        back to the classic registry/prefs panel set). Node ``model`` keeps the
        per-node override; ``resolved_model`` is what would actually run.
        """
        active_id = state.prefs.get("active_workflow_id")
        wf = workflows.load_workflow(active_id) if active_id else None
        if wf is None:
            return {"active_workflow_id": active_id, "workflow": None}
        data = wf.to_dict()
        for node in data["nodes"]:
            node["resolved_model"] = (
                node.get("model") or opencode_cfg.resolve_model(node.get("agent") or "")
            )
        return {"active_workflow_id": active_id, "workflow": data}

    @router.put("/api/active-workflow")
    async def api_active_workflow_set(body: ActiveWorkflowIn) -> dict:
        wf = workflows.load_workflow(body.workflow_id)
        if wf is None:
            raise HTTPException(404, f"workflow not found: {body.workflow_id}")
        state.update_prefs({"active_workflow_id": wf.id})
        return {"ok": True, "active_workflow_id": wf.id}

    @router.delete("/api/active-workflow")
    async def api_active_workflow_clear() -> dict:
        state.update_prefs({"active_workflow_id": None})
        return {"ok": True, "active_workflow_id": None}

    # ---- dispatch ---------------------------------------------------------

    @router.post("/api/dispatch")
    async def api_dispatch(body: DispatchIn) -> dict:
        prompt = (body.prompt or "").strip()
        if not prompt:
            raise HTTPException(400, "prompt must not be empty")
        # The active workflow is the authoritative graph for Home commands:
        # never silently fall back to a different graph or a plain agent list.
        active_id = state.prefs.get("active_workflow_id")
        if active_id:
            wf = workflows.load_workflow(active_id)
            if wf is None:
                raise HTTPException(409,
                                   f"active workflow {active_id!r} is missing — "
                                   "clear or re-activate it in the Workflow Designer")
            errors = workflows.validate_workflow(wf)
            if errors:
                raise HTTPException(409, {"errors": errors})
            run_id = workflow_engine.start_run(
                wf, initial_state={"user_prompt": prompt})
            state.push_usermsg(
                "master", f"▶ workflow {active_id}: dispatched (run {run_id})")
            return {"ok": True, "mode": "workflow", "run_id": run_id,
                    "workflow_id": active_id,
                    "nodes": [n.id for n in wf.nodes]}
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

    @router.put("/api/tasks/{name}/role")
    async def api_task_role(name: str, body: TaskRoleIn) -> dict:
        """Set/clear a temporary task-level role override.

        The override is written to the task node's ``role`` frontmatter field
        (empty string clears it). It never touches ``roles.json`` — the agent's
        persistent role assignments are unchanged. Unknown role ids are
        rejected with 409 before any write.
        """
        path = _task_path(state_vault, name)
        role_id = (body.role or "").strip()
        if role_id and roles.get_role(role_id) is None:
            raise HTTPException(409, f"unknown role {role_id!r}")
        new_fields = update_task(path, "web-ui-role-override", {"role": role_id})
        return {"name": name, "role": new_fields.get("role", "")}

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
                         "modes", "roles", "profile", "graph", "security"],
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

    # ---- roles (many-to-many, model-independent) --------------------------

    @router.get("/api/settings/roles")
    async def api_settings_roles() -> dict:
        return {"roles": ui_settings.list_roles(),
                "assignments": ui_settings.role_assignments()}

    @router.post("/api/settings/roles")
    async def api_settings_create_role(body: RoleCreateIn) -> dict:
        try:
            role = ui_settings.create_role(
                body.id, name=body.name, description=body.description,
                responsibilities=body.responsibilities, tools=body.tools,
                permissions=body.permissions, rules=body.rules,
                expected_outputs=body.expected_outputs)
        except roles.RoleError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, **role}

    @router.get("/api/settings/agents/{agent}/roles")
    async def api_settings_agent_roles(agent: str) -> dict:
        spec = AGENT_SPEC_BY_AGENT.get(agent)
        if spec is None:
            raise HTTPException(404, f"unknown agent key {agent!r}")
        return {"agent": agent, "role_ids": roles.roles_for_agent(agent)}

    @router.put("/api/settings/agents/{agent}/roles")
    async def api_settings_assign_roles(agent: str, body: RolesAssignIn) -> dict:
        spec = AGENT_SPEC_BY_AGENT.get(agent)
        if spec is None:
            raise HTTPException(404, f"unknown agent key {agent!r}")
        try:
            role_ids = ui_settings.assign_roles(agent, body.role_ids)
        except roles.RoleError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, "agent": agent, "role_ids": role_ids}

    # ---- prompt library (reusable, role-typed prompt profiles) -----------

    def _prompt_meta(profile: prompt_library.PromptProfile) -> dict:
        """UI metadata + resolved model requirements (no prompt text)."""
        meta = profile.meta_dict()
        meta["model_preferences"] = (
            prompt_library.preferences_for_profile(profile).to_dict())
        return meta

    @router.get("/api/prompts")
    async def api_prompts(role: Optional[str] = None) -> dict:
        """List prompt profile metadata, optionally suggested for a role/agent.

        ``?role=developer`` maps keywords/role-store ids to prompt roles via
        :func:`prompt_library.suggest_prompts_for_role` (deterministic, no LLM).
        The list returns UI metadata only (no prompt text); the full profile —
        including its prompt — is available from ``GET /api/prompts/{id}``.
        """
        profiles = (prompt_library.suggest_prompts_for_role(role)
                    if (role and role.strip())
                    else prompt_library.list_prompts())
        return {
            "prompts": [_prompt_meta(p) for p in profiles],
            "roles": list(prompt_library.list_prompt_roles()),
        }

    @router.get("/api/prompts/recommend")
    async def api_prompts_recommend_meta() -> dict:
        """Task-classification metadata: categories, roles, and the built-in
        deterministic task → prompt example mappings (no LLM)."""
        examples = [
            {"task": "security audit", "role": "security_engineer",
             "prompt_id": "security-auditor"},
            {"task": "threat model", "role": "security_engineer",
             "prompt_id": "security-threat-modeler"},
            {"task": "implement feature", "role": "software_engineer",
             "prompt_id": "software-engineer-expert"},
            {"task": "write code", "role": "software_engineer",
             "prompt_id": "software-engineer"},
            {"task": "design architecture", "role": "software_architect",
             "prompt_id": "system-architect"},
            {"task": "debug error", "role": "debugger",
             "prompt_id": "debugger-root-cause"},
            {"task": "find bugs", "role": "code_reviewer",
             "prompt_id": "code-reviewer"},
            {"task": "CI/CD", "role": "devops_engineer",
             "prompt_id": "devops-cicd"},
            {"task": "multi-agent workflow", "role": "orchestrator",
             "prompt_id": "orchestrator-multi-agent"},
        ]
        return {
            "categories": list(prompt_library.TASK_CATEGORIES),
            "roles": list(prompt_library.list_prompt_roles()),
            "examples": examples,
        }

    @router.post("/api/prompts/recommend")
    async def api_prompts_recommend(body: PromptRecommendIn) -> dict:
        """Rank prompt profiles for a task (deterministic matching, no LLM).

        Returns the task classification plus ``{prompt_id, score, reason}``
        entries. ``score`` is a deterministic matching score (not ML confidence).
        """
        task = prompt_library.classify_task(body.task or "")
        recs = prompt_library.recommend_prompts(
            task, role=body.role, capabilities=body.capabilities,
            complexity=body.complexity, risk=body.risk)
        return {
            "task": task.to_dict(),
            "recommendations": [r.to_dict() for r in recs],
        }

    @router.get("/api/prompts/{prompt_id}")
    async def api_prompt(prompt_id: str) -> dict:
        try:
            profile = prompt_library.get_prompt(prompt_id)
        except prompt_library.PromptError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"prompt": profile.to_dict()}

    # ---- model capabilities + recommendation (provider-neutral) ---------

    @router.get("/api/models")
    async def api_models(provider: str = "") -> dict:
        """Model Registry catalog (Phase 3) — metadata only, no credentials."""
        if provider:
            models = model_registry.list_models_by_provider(provider)
        else:
            models = model_registry.list_models()
        return {
            "models": [m.to_dict() for m in models],
            "providers": model_registry.model_providers(),
        }

    @router.get("/api/models/capabilities")
    async def api_models_capabilities() -> dict:
        """Provider-neutral model capability archetypes (Phase 2 metadata).

        These are capability shapes, not providers; the Phase 3 registry maps
        concrete models onto them.
        """
        return {"models": [m.to_dict() for m in prompt_library.model_archetypes()]}

    # ``:path`` so provider/model ids (e.g. ``opencode/big-pickle``) resolve.
    # Registered after /api/models and /api/models/capabilities so those exact
    # routes always win (FastAPI matches in registration order).
    @router.get("/api/models/{model_id:path}")
    async def api_model(model_id: str) -> dict:
        try:
            spec = model_registry.get_model(model_id)
        except model_registry.ModelError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"model": spec.to_dict()}

    @router.post("/api/models/recommend")
    async def api_models_recommend(body: ModelRecommendIn) -> dict:
        """Rank models for a task/prompt (deterministic, never changes a
        user's model).

        Phase 2 compat: when ``available_models`` (capability dicts) is
        supplied those are ranked as before. Otherwise the Phase 3 registry
        catalog is ranked via :func:`select_models` — an ``explicit_model`` is
        always preserved and flagged ``explicit``.
        """
        prompt_id = body.prompt_profile or body.prompt_id
        profile = None
        if prompt_id:
            try:
                profile = prompt_library.get_prompt(prompt_id)
            except prompt_library.PromptError as exc:
                raise HTTPException(404, str(exc)) from exc
        requirements = prompt_library.recommend_model_capabilities(
            task=body.task, prompt_profile=profile)

        if body.available_models:
            # Phase 2 path: rank the caller-supplied capability profiles.
            recs = prompt_library.recommend_model_capabilities(
                task=body.task, prompt_profile=profile,
                available_models=body.available_models)
            return {
                "requirements": requirements.to_dict(),
                "recommendations": [r.to_dict() for r in recs],
            }

        # Phase 3 path: rank the registry catalog.
        recs = model_registry.select_models(
            requirements=requirements,
            provider=body.provider,
            explicit_model=body.explicit_model,
            hard_requirements=body.hard_requirements,
        )
        return {
            "requirements": requirements.to_dict(),
            "recommendations": [r.to_dict() for r in recs],
        }

    # ---- BYOK connections (Phase 4) ---------------------------------------

    def _conn_error(exc: Exception) -> HTTPException:
        """Map connection-layer errors to safe, secret-free HTTP responses."""
        from scripts.core.model_connections.errors import (
            CredentialError,
            DuplicateConnectionError,
            ResolutionError,
            UnknownConnectionError,
            UnknownProviderError,
        )
        if isinstance(exc, UnknownConnectionError):
            return HTTPException(404, str(exc))
        if isinstance(exc, DuplicateConnectionError):
            return HTTPException(409, str(exc))
        if isinstance(exc, (UnknownProviderError, CredentialError,
                            ResolutionError, ConnectionError)):
            return HTTPException(422, str(exc))
        return HTTPException(500, "connection operation failed")

    @router.get("/api/connections")
    async def api_connections() -> dict:
        """Connection metadata only — never a secret."""
        return {
            "connections": [c.to_dict() for c in model_connections.list_connections()],
            "providers": model_connections.providers.provider_meta(),
        }

    @router.post("/api/connections")
    async def api_connections_create(body: ConnectionCreateIn) -> dict:
        try:
            connection = model_connections.create_connection(
                body.provider, body.display_name or "",
                api_key=body.api_key, endpoint=body.endpoint or "",
                deployment=body.deployment or "", default=body.default,
                credential_type=body.credential_type or "api_key",
                connection_id=body.connection_id)
        except model_connections.ConnectionError as exc:
            raise _conn_error(exc) from exc
        return {"connection": connection.to_dict()}

    @router.get("/api/connections/{connection_id}")
    async def api_connection_get(connection_id: str) -> dict:
        try:
            return {"connection": model_connections.get_connection(connection_id).to_dict()}
        except model_connections.ConnectionError as exc:
            raise _conn_error(exc) from exc

    @router.put("/api/connections/{connection_id}")
    async def api_connection_update(connection_id: str, body: ConnectionUpdateIn) -> dict:
        try:
            connection = model_connections.update_connection(
                connection_id,
                display_name=body.display_name, endpoint=body.endpoint,
                deployment=body.deployment, api_key=body.api_key,
                default=body.default, credential_type=body.credential_type,
                status=body.status)
        except model_connections.ConnectionError as exc:
            raise _conn_error(exc) from exc
        return {"connection": connection.to_dict()}

    @router.delete("/api/connections/{connection_id}")
    async def api_connection_delete(connection_id: str) -> dict:
        try:
            model_connections.delete_connection(connection_id)
        except model_connections.ConnectionError as exc:
            raise _conn_error(exc) from exc
        return {"ok": True}

    @router.post("/api/connections/{connection_id}/validate")
    async def api_connection_validate(connection_id: str) -> dict:
        """Configuration-based validation (no network call, no secret)."""
        try:
            return model_connections.validate_connection(connection_id)
        except model_connections.ConnectionError as exc:
            raise _conn_error(exc) from exc

    @router.post("/api/connections/resolve")
    async def api_connections_resolve(body: ConnectionResolveIn) -> dict:
        """Resolve a node's model/connection to its runtime configuration.

        Returns metadata + a masked credential flag — never the secret.
        """
        try:
            resolution = model_connections.resolve(
                model=body.model, connection_id=body.connection_id)
        except model_connections.ConnectionError as exc:
            raise _conn_error(exc) from exc
        return {"resolution": resolution.to_dict()}

    # ---- project profile (repository analysis) ----------------------------

    @router.get("/api/settings/profile")
    async def api_settings_profile() -> dict:
        profile = analyze_repository(_REPO_ROOT)
        reasons = suggested_role_reasons(profile)
        return {
            "root": str(profile.root),
            "technologies": list(profile.technologies),
            "detected_roles": list(profile.detected_roles),
            "suggested_roles": [
                {"id": rid, "reason": reasons.get(rid, "")}
                for rid in suggest_roles(profile)
            ],
            "approved_roles": list(profile.approved_roles),
            "manifests": {k: list(v) for k, v in profile.manifests.items()},
            "instruction_files": sorted(profile.instructions),
        }

    # ---- workflows (Agent Workspace / LangGraph-style designer) -----------

    def _wf_summary(wf: workflows.Workflow) -> dict:
        return {
            "id": wf.id,
            "name": wf.name,
            "project": wf.project,
            "nodes": len(wf.nodes),
            "edges": len(wf.edges),
        }

    @router.get("/api/workflows")
    async def api_workflows() -> dict:
        return {"workflows": [_wf_summary(w) for w in workflows.list_workflows()]}

    @router.get("/api/workflows/templates")
    async def api_workflow_templates() -> dict:
        return {"templates": workflows.list_templates()}

    @router.get("/api/workflows/recommend")
    async def api_workflow_recommend(agents: int = 4) -> dict:
        try:
            return workflows.recommend_workflow(n_agents=agents)
        except workflows.WorkflowError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/workflows/from-template/{name}")
    async def api_workflow_from_template(name: str) -> dict:
        wf = workflows.get_template(name)
        if wf is None:
            raise HTTPException(404, f"unknown template {name!r}")
        return {"workflow": wf.to_dict()}

    @router.get("/api/workflows/{workflow_id}")
    async def api_workflow_get(workflow_id: str) -> dict:
        wf = workflows.load_workflow(workflow_id)
        if wf is None:
            raise HTTPException(404, f"workflow not found: {workflow_id}")
        return {"workflow": wf.to_dict()}

    @router.put("/api/workflows/{workflow_id}")
    async def api_workflow_save(workflow_id: str, body: WorkflowIn) -> dict:
        try:
            wf = workflows.Workflow.from_dict(body.model_dump())
            wf.id = workflow_id
            saved = workflows.save_workflow(wf)
        except workflows.WorkflowError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True, "workflow": saved.to_dict()}

    @router.delete("/api/workflows/{workflow_id}")
    async def api_workflow_delete(workflow_id: str) -> dict:
        return {"ok": True, "deleted": workflows.delete_workflow(workflow_id)}

    @router.post("/api/workflows/{workflow_id}/duplicate")
    async def api_workflow_duplicate(workflow_id: str) -> dict:
        try:
            wf = workflows.duplicate_workflow(workflow_id)
        except workflows.WorkflowError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"ok": True, "workflow": wf.to_dict()}

    @router.get("/api/workflows/{workflow_id}/validate")
    async def api_workflow_validate(workflow_id: str) -> dict:
        wf = workflows.load_workflow(workflow_id)
        if wf is None:
            raise HTTPException(404, f"workflow not found: {workflow_id}")
        errors = workflows.validate_workflow(wf)
        return {"valid": not errors, "errors": errors}

    @router.post("/api/workflows/{workflow_id}/run")
    async def api_workflow_run(workflow_id: str, body: WorkflowRunIn) -> dict:
        wf = workflows.load_workflow(workflow_id)
        if wf is None:
            raise HTTPException(404, f"workflow not found: {workflow_id}")
        errors = workflows.validate_workflow(wf)
        if errors:
            raise HTTPException(409, {"errors": errors})
        run_id = workflow_engine.start_run(
            wf, initial_state=body.initial_state, repo_root=_REPO_ROOT)
        return {"ok": True, "run_id": run_id}

    @router.post("/api/workflows/{workflow_id}/dry-run")
    async def api_workflow_dry_run(workflow_id: str, body: dict | None = None) -> dict:
        """Preview the execution plan without dispatching any agent.

        Accepts the workflow payload directly (so unsaved edits can be
        previewed) and falls back to the persisted workflow when no body is
        given. Validation is authoritative here, exactly as for a real run.
        """
        if isinstance(body, dict) and (body.get("nodes") or body.get("edges")
                                       or body.get("entry") or body.get("id")):
            wf = workflows.Workflow.from_dict(body)
            wf.id = workflow_id
        else:
            wf = workflows.load_workflow(workflow_id)
            if wf is None:
                raise HTTPException(404, f"workflow not found: {workflow_id}")
        errors = workflows.validate_workflow(wf)
        if errors:
            raise HTTPException(409, {"errors": errors})
        plan = workflow_engine.simulate_workflow(wf, repo_root=_REPO_ROOT)
        return {"ok": True, **plan}

    @router.get("/api/workflows/{workflow_id}/runs")
    async def api_workflow_runs(workflow_id: str) -> dict:
        return {"runs": [r for r in workflow_engine.list_runs()
                         if r["workflow_id"] == workflow_id]}

    @router.get("/api/workflows/runs/{run_id}")
    async def api_workflow_run_status(run_id: str) -> dict:
        runner = workflow_engine.get_run(run_id)
        if runner is None:
            raise HTTPException(404, f"run not found: {run_id}")
        return runner.snapshot()

    @router.post("/api/workflows/runs/{run_id}/cancel")
    async def api_workflow_run_cancel(run_id: str) -> dict:
        return {"ok": True, "cancelled": workflow_engine.cancel_run(run_id)}

    # ---- preferences ------------------------------------------------------

    @router.get("/api/prefs")
    async def api_get_prefs() -> dict:
        return dict(state.prefs)

    @router.post("/api/prefs")
    async def api_set_prefs(body: dict) -> dict:
        return state.update_prefs(body)

    return router


__all__ = ["create_router", "HUB"]
"""Workflow model — project-specific multi-agent graphs (n8n-style, LangGraph-semantics).

A :class:`Workflow` references reusable Agents / Roles / Models but never
redefines them. It is a **separate concern** from the control-plane identity
(``AgentSpec``), the role store (``roles.json``) and the runtime model config
(``opencode.json``):

    * ``Agent``  — a node's ``agent`` field names an existing agent key.
    * ``Role``   — a node's ``roles`` tuple names existing role ids (an
      in-workflow override of the agent's persistent assignments).
    * ``Model``  — a node's ``model`` field is an optional runtime override;
      empty means "Auto / runtime default" (resolved from ``opencode.json``).

Workflows persist as JSON files under ``workflows/`` (``$ZOVA_WORKFLOWS``
override), one file per workflow id. Nothing here ever edits ``AgentSpec``
modules, ``roles.json``, or ``opencode.json`` — and API keys never appear in a
workflow (only provider/model ids).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.core import opencode_cfg
from scripts.core import prompt_library
from scripts.core import roles
from scripts.core.agents import AGENT_SPEC_BY_AGENT, AGENTS, PROJECT_ROOT

# Valid edge conditions. "" (empty) == unconditional forward flow.
EDGE_CONDITIONS = ("", "success", "failure")

# Valid node kinds.
NODE_KINDS = ("agent", "end")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Placeholder ids that must never be persisted. The Workflow Designer's initial
# in-memory graph uses "untitled" until the user names it; the backend refuses
# to write that placeholder so it can never leak into workflows/*.json.
RESERVED_WORKFLOW_IDS = frozenset({"untitled"})


class WorkflowError(ValueError):
    """Raised for invalid workflow operations (mapped to HTTP 409/422)."""


@dataclass
class WorkflowNode:
    """One node in a workflow graph — an *instance* reference to an agent.

    The same agent may appear in many nodes (Developer #1 / #2 / #3), each
    with its own roles / model / instructions / tools. ``kind`` is ``agent``
    (dispatch an agent) or ``end`` (a terminal no-op that records completion).
    """

    id: str
    label: str = ""
    agent: str = ""               # opencode agent key; "" = no agent (end/pass)
    kind: str = "agent"           # "agent" | "end"
    model: str = ""               # runtime override; "" = Auto / runtime default
    roles: tuple[str, ...] = ()
    instructions: str = ""
    prompt_profile: str = ""      # optional prompt-library id (source of instruction)
    task: dict = field(default_factory=dict)  # optional Task classification metadata
    tools: tuple[str, ...] = ()
    enabled: bool = True
    x: float = 0.0
    y: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowNode":
        def _tup(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            return tuple(str(x) for x in value)

        return cls(
            id=str(data.get("id") or ""),
            label=str(data.get("label") or ""),
            agent=str(data.get("agent") or ""),
            kind=str(data.get("kind") or "agent"),
            model=str(data.get("model") or ""),
            roles=_tup("roles"),
            instructions=str(data.get("instructions") or ""),
            prompt_profile=str(data.get("prompt_profile") or ""),
            task=dict(data.get("task") or {}),
            tools=_tup("tools"),
            enabled=bool(data.get("enabled", True)),
            x=float(data.get("x") or 0.0),
            y=float(data.get("y") or 0.0),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "agent": self.agent,
            "kind": self.kind,
            "model": self.model,
            "roles": list(self.roles),
            "instructions": self.instructions,
            "prompt_profile": self.prompt_profile,
            "task": self.task,
            "tools": list(self.tools),
            "enabled": self.enabled,
            "x": self.x,
            "y": self.y,
        }


@dataclass
class WorkflowEdge:
    """A directed edge between nodes; ``condition`` in {""|"success"|"failure"}."""

    source: str
    target: str
    condition: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowEdge":
        return cls(
            source=str(data.get("source") or ""),
            target=str(data.get("target") or ""),
            condition=str(data.get("condition") or ""),
        )

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "condition": self.condition}


@dataclass
class Workflow:
    """A project-specific workflow graph + its persisted state/settings."""

    id: str
    name: str = ""
    project: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    entry: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Workflow":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            project=str(data.get("project") or ""),
            nodes=[WorkflowNode.from_dict(n) for n in (data.get("nodes") or [])],
            edges=[WorkflowEdge.from_dict(e) for e in (data.get("edges") or [])],
            entry=[str(x) for x in (data.get("entry") or [])],
            state=dict(data.get("state") or {}),
            settings=dict(data.get("settings") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "project": self.project,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "entry": list(self.entry),
            "state": self.state,
            "settings": self.settings,
        }

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}


# ---------------------------------------------------------------- ids / paths


def normalize_workflow_id(workflow_id: str) -> str:
    """Normalize a workflow id into a safe, filesystem-friendly slug.

    Rejects path separators, ``..`` and other traversal/unsafe characters so
    an id can never escape ``workflows/``. Only ``[a-z0-9._-]`` (plus a leading
    alnum) is accepted after lowercasing and space-to-dash replacement.
    """
    slug = (workflow_id or "").strip().lower().replace(" ", "-")
    if not _ID_RE.match(slug):
        raise WorkflowError(
            f"invalid workflow id {workflow_id!r} (use [a-z0-9._-], no path separators)"
        )
    return slug


def workflows_dir(repo_root: Path | None = None) -> Path:
    env = os.environ.get("ZOVA_WORKFLOWS", "").strip()
    if env:
        return Path(env).expanduser()
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    return root / "workflows"


def workflow_path(workflow_id: str, repo_root: Path | None = None) -> Path:
    return workflows_dir(repo_root) / f"{normalize_workflow_id(workflow_id)}.json"


# ---------------------------------------------------------------- persistence


def load_workflow(workflow_id: str, repo_root: Path | None = None) -> Workflow | None:
    path = workflow_path(workflow_id, repo_root)
    try:
        if path.is_file():
            return Workflow.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None
    return None


def list_workflows(repo_root: Path | None = None) -> list[Workflow]:
    out: list[Workflow] = []
    directory = workflows_dir(repo_root)
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            wf = Workflow.from_dict(data)
            if wf.id:
                out.append(wf)
        except (OSError, ValueError, TypeError):
            continue
    return out


def save_workflow(workflow: Workflow, repo_root: Path | None = None) -> Workflow:
    """Persist a workflow atomically (temp + ``os.replace``)."""
    workflow.id = normalize_workflow_id(workflow.id)
    if workflow.id in RESERVED_WORKFLOW_IDS:
        raise WorkflowError(
            f"{workflow.id!r} is a placeholder, not a persistent workflow id — "
            "give the workflow a real id before saving"
        )
    path = workflow_path(workflow.id, repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(workflow.to_dict(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return workflow


def delete_workflow(workflow_id: str, repo_root: Path | None = None) -> bool:
    path = workflow_path(workflow_id, repo_root)
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False


def duplicate_workflow(workflow_id: str, repo_root: Path | None = None,
                       new_id: str | None = None) -> Workflow:
    wf = load_workflow(workflow_id, repo_root)
    if wf is None:
        raise WorkflowError(f"unknown workflow {workflow_id!r}")
    base = normalize_workflow_id(new_id) if new_id else normalize_workflow_id(workflow_id)
    candidate = base
    i = 2
    while load_workflow(candidate, repo_root) is not None:
        candidate = f"{base}-copy{i}"
        i += 1
    wf.id = candidate
    wf.name = f"{wf.name} (copy)" if wf.name else candidate
    return save_workflow(wf, repo_root)


def export_workflow(workflow_id: str, repo_root: Path | None = None) -> dict | None:
    wf = load_workflow(workflow_id, repo_root)
    return wf.to_dict() if wf is not None else None


def import_workflow(data: dict, repo_root: Path | None = None,
                    workflow_id: str | None = None) -> Workflow:
    if not isinstance(data, dict):
        raise WorkflowError("workflow import must be a JSON object")
    wf = Workflow.from_dict(data)
    if workflow_id:
        wf.id = normalize_workflow_id(workflow_id)
    else:
        wf.id = normalize_workflow_id(wf.id or "imported")
    return save_workflow(wf, repo_root)


# ---------------------------------------------------------------- validation


def validate_workflow(workflow: Workflow, repo_root: Path | None = None) -> list[dict]:
    """Graph + reference validation. Returns human-readable ``{node, message}`` errors.

    Detects: missing/duplicate ids, missing/unknown agent, unknown role,
    malformed model, invalid edge (unknown ref, self-loop, bad condition),
    disconnected nodes, unsupported (unconditional) cycles / infinite-loop
    risk, and missing start node. An empty list means the workflow may run.
    """
    errors: list[dict] = []
    node_map = {n.id: n for n in workflow.nodes}
    role_store = roles.load_roles(repo_root)
    known_roles = set(role_store.get("roles", {}))
    known_agents = set(AGENT_SPEC_BY_AGENT)

    # ids
    seen: set[str] = set()
    for node in workflow.nodes:
        if not node.id:
            errors.append({"node": None, "message": "a node has an empty id"})
        elif node.id in seen:
            errors.append({"node": node.id, "message": f"duplicate node id {node.id!r}"})
        seen.add(node.id)

    for node in workflow.nodes:
        if node.kind not in NODE_KINDS:
            errors.append({"node": node.id, "message": f"unknown node kind {node.kind!r}"})
            continue
        if node.kind == "agent":
            if not node.agent:
                errors.append({"node": node.id, "message": "missing Agent (set an agent key)"})
            elif node.agent not in known_agents:
                errors.append({"node": node.id, "message": f"Agent {node.agent!r} does not exist"})
        for rid in node.roles:
            if rid not in known_roles:
                errors.append({"node": node.id, "message": f"Role {rid!r} does not exist"})
        if node.prompt_profile:
            try:
                prompt_library.get_prompt(node.prompt_profile)
            except prompt_library.PromptError:
                errors.append({"node": node.id,
                               "message": f"Prompt profile {node.prompt_profile!r} does not exist"})
        if node.model:
            try:
                opencode_cfg.validate_model_id(node.model)
            except opencode_cfg.ConfigError as exc:
                errors.append({"node": node.id, "message": f"Model {node.model!r} is invalid ({exc})"})

    # edges
    for edge in workflow.edges:
        if edge.source not in node_map:
            errors.append({"node": None, "message": f"edge references missing node {edge.source!r}"})
        if edge.target not in node_map:
            errors.append({"node": None, "message": f"edge references missing node {edge.target!r}"})
        if edge.source and edge.source == edge.target:
            errors.append({"node": edge.source, "message": "self-loop edge is not allowed"})
        if edge.condition not in EDGE_CONDITIONS:
            errors.append({"node": edge.source, "message":
                           f"invalid routing condition {edge.condition!r} (use success/failure)"})

    if not workflow.nodes:
        return [{"node": None, "message": "workflow has no nodes"}]

    enabled_ids = {n.id for n in workflow.nodes if n.enabled}
    if not enabled_ids:
        return errors + [{"node": None, "message": "all nodes are disabled"}]

    # disconnected nodes (a node with no edges at all in a >1 node workflow)
    if len(enabled_ids) > 1:
        connected: set[str] = set()
        for edge in workflow.edges:
            connected.add(edge.source)
            connected.add(edge.target)
        for node in workflow.nodes:
            if node.enabled and node.id not in connected:
                errors.append({"node": node.id, "message": "disconnected node (no edges)"})

    # start node (effective entry: explicit entry, else zero-in-degree enabled nodes)
    starts = effective_entry(workflow)
    if not starts:
        errors.append({"node": None, "message":
                       "missing start node (no enabled node without incoming edges; "
                       "set 'entry' for cyclic workflows)"})

    # unconditional cycle -> infinite-loop risk (conditional edges may break cycles)
    if _unconditional_cycle(workflow):
        errors.append({"node": None, "message":
                       "unsupported cycle: a loop must include a conditional (success/failure) edge"})

    return errors


def effective_entry(workflow: Workflow) -> list[str]:
    """Effective start nodes: explicit ``entry`` if set, else zero-in-degree nodes.

    Explicit entry is required for cyclic graphs (a retry loop's first node has
    a conditional edge back into it, so it has non-zero in-degree); DAGs infer
    their starts from nodes with no incoming edges.
    """
    if workflow.entry:
        known = workflow.node_ids()
        return [nid for nid in workflow.entry if nid in known]
    has_incoming = {e.target for e in workflow.edges}
    return [n.id for n in workflow.nodes if n.enabled and n.id not in has_incoming]


def _unconditional_cycle(workflow: Workflow) -> bool:
    """Detect a cycle in the subgraph of unconditional edges only.

    A cycle made purely of unconditional (``""``) edges can never terminate;
    conditional edges (``success``/``failure``) are allowed to close a loop
    because the runtime bounds it with ``max_iterations``.
    """
    adj: dict[str, list[str]] = {}
    for edge in workflow.edges:
        if edge.condition == "":
            adj.setdefault(edge.source, []).append(edge.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def visit(node_id: str) -> bool:
        color[node_id] = GRAY
        for nxt in adj.get(node_id, []):
            c = color.get(nxt, WHITE)
            if c == GRAY:
                return True
            if c == WHITE and visit(nxt):
                return True
        color[node_id] = BLACK
        return False

    for node in workflow.nodes:
        if color.get(node.id, WHITE) == WHITE:
            if visit(node.id):
                return True
    return False


# ---------------------------------------------------------------- templates

_TEMPLATE_AGENTS = [agent for _tag, _name, agent in AGENTS if agent]


def _node(nid: str, role: str, agent: str, label: str, kind: str = "agent",
          x: float = 0.0, y: float = 0.0) -> WorkflowNode:
    return WorkflowNode(
        id=nid, label=label, agent=agent, kind=kind, roles=(role,),
        x=x, y=y,
    )


def _chain(steps: list[tuple[str, str, str]]) -> tuple[list[WorkflowNode], list[WorkflowEdge]]:
    """Build a linear chain of (id, role, label) steps, round-robin agents."""
    nodes: list[WorkflowNode] = []
    edges: list[WorkflowEdge] = []
    for i, (nid, role, label) in enumerate(steps):
        agent = _TEMPLATE_AGENTS[i % len(_TEMPLATE_AGENTS)]
        nodes.append(_node(nid, role, agent, label, x=0.0, y=i * 120.0))
        if i:
            edges.append(WorkflowEdge(steps[i - 1][0], nid))
    return nodes, edges


def _template(name: str, nodes: list[WorkflowNode], edges: list[WorkflowEdge],
              project: str = "") -> Workflow:
    return Workflow(
        id=f"template-{name.lower().replace(' ', '-')}", name=name, project=project,
        nodes=nodes, edges=edges, settings={"max_iterations": 3},
    )


def get_template(name: str) -> Workflow | None:
    """Instantiate a predefined template by slug. Returns ``None`` if unknown."""
    name = (name or "").strip().lower().replace(" ", "-")
    if name == "sequential":
        nodes, edges = _chain([
            ("architect", "software-architect", "Architect"),
            ("developer", "python-developer", "Developer"),
            ("tester", "qa-engineer", "Tester"),
            ("reviewer", "code-reviewer", "Reviewer"),
        ])
        return _template("Sequential Coding Pipeline", nodes, edges)
    if name == "parallel":
        arch = _node("architect", "software-architect", _TEMPLATE_AGENTS[0], "Architect",
                     x=0.0, y=0.0)
        backend = _node("backend", "python-developer", _TEMPLATE_AGENTS[1], "Backend",
                        x=160.0, y=-120.0)
        frontend = _node("frontend", "fastapi-developer", _TEMPLATE_AGENTS[2], "Frontend",
                         x=160.0, y=0.0)
        security = _node("security", "security-engineer", _TEMPLATE_AGENTS[3], "Security",
                         x=160.0, y=120.0)
        reviewer = _node("reviewer", "code-reviewer", _TEMPLATE_AGENTS[4], "Reviewer",
                         x=320.0, y=0.0)
        nodes = [arch, backend, frontend, security, reviewer]
        edges = [
            WorkflowEdge("architect", "backend"),
            WorkflowEdge("architect", "frontend"),
            WorkflowEdge("architect", "security"),
            WorkflowEdge("backend", "reviewer"),
            WorkflowEdge("frontend", "reviewer"),
            WorkflowEdge("security", "reviewer"),
        ]
        return _template("Parallel Engineering", nodes, edges)
    if name == "supervisor":
        sup1 = _node("supervisor_1", "software-architect", _TEMPLATE_AGENTS[0], "Supervisor",
                     x=0.0, y=0.0)
        a = _node("agent_a", "python-developer", _TEMPLATE_AGENTS[1], "Agent A",
                  x=140.0, y=-100.0)
        b = _node("agent_b", "fastapi-developer", _TEMPLATE_AGENTS[2], "Agent B",
                  x=140.0, y=0.0)
        c = _node("agent_c", "qa-engineer", _TEMPLATE_AGENTS[3], "Agent C",
                  x=140.0, y=100.0)
        sup2 = _node("supervisor_2", "code-reviewer", _TEMPLATE_AGENTS[0], "Supervisor",
                     x=280.0, y=0.0)
        nodes = [sup1, a, b, c, sup2]
        edges = [
            WorkflowEdge("supervisor_1", "agent_a"),
            WorkflowEdge("supervisor_1", "agent_b"),
            WorkflowEdge("supervisor_1", "agent_c"),
            WorkflowEdge("agent_a", "supervisor_2"),
            WorkflowEdge("agent_b", "supervisor_2"),
            WorkflowEdge("agent_c", "supervisor_2"),
        ]
        return _template("Supervisor", nodes, edges)
    if name == "router":
        router = _node("router", "software-architect", _TEMPLATE_AGENTS[0], "Router",
                       x=0.0, y=0.0)
        code = _node("code", "python-developer", _TEMPLATE_AGENTS[1], "Code",
                     x=160.0, y=-90.0)
        docs = _node("docs", "code-reviewer", _TEMPLATE_AGENTS[2], "Docs",
                     x=160.0, y=0.0)
        research = _node("research", "ai-agent-engineer", _TEMPLATE_AGENTS[3], "Research",
                         x=160.0, y=90.0)
        nodes = [router, code, docs, research]
        edges = [
            WorkflowEdge("router", "code"),
            WorkflowEdge("router", "docs"),
            WorkflowEdge("router", "research"),
        ]
        return _template("Router", nodes, edges)
    if name == "hierarchical":
        pm = _node("pm", "software-architect", _TEMPLATE_AGENTS[0], "Project Manager",
                   x=0.0, y=0.0)
        team1 = _node("team_1", "python-developer", _TEMPLATE_AGENTS[1], "Team 1",
                      x=160.0, y=-90.0)
        team2 = _node("team_2", "fastapi-developer", _TEMPLATE_AGENTS[2], "Team 2",
                      x=160.0, y=0.0)
        team3 = _node("team_3", "qa-engineer", _TEMPLATE_AGENTS[3], "Team 3",
                      x=160.0, y=90.0)
        nodes = [pm, team1, team2, team3]
        edges = [
            WorkflowEdge("pm", "team_1"),
            WorkflowEdge("pm", "team_2"),
            WorkflowEdge("pm", "team_3"),
        ]
        return _template("Hierarchical", nodes, edges)
    if name == "reflection":
        dev = _node("developer", "python-developer", _TEMPLATE_AGENTS[0], "Developer",
                    x=0.0, y=0.0)
        reviewer = _node("reviewer", "code-reviewer", _TEMPLATE_AGENTS[1], "Reviewer",
                         x=140.0, y=0.0)
        done = _node("done", "", "", "done", kind="end", x=280.0, y=0.0)
        nodes = [dev, reviewer, done]
        edges = [
            WorkflowEdge("developer", "reviewer"),
            WorkflowEdge("reviewer", "done", condition="success"),
            WorkflowEdge("reviewer", "developer", condition="failure"),
        ]
        wf = _template("Reflection", nodes, edges)
        wf.entry = ["developer"]
        wf.settings["max_iterations"] = 3
        return wf
    if name == "parallel-specialists":
        planner = _node("planner", "software-architect", _TEMPLATE_AGENTS[0], "Planner",
                        x=0.0, y=0.0)
        researcher = _node("researcher", "ai-agent-engineer", _TEMPLATE_AGENTS[1], "Researcher",
                           x=170.0, y=-90.0)
        developer = _node("developer", "python-developer", _TEMPLATE_AGENTS[2], "Developer",
                          x=170.0, y=0.0)
        analyst = _node("analyst", "code-reviewer", _TEMPLATE_AGENTS[3], "Analyst",
                        x=170.0, y=90.0)
        aggregator = _node("aggregator", "software-architect", _TEMPLATE_AGENTS[4], "Aggregator",
                           x=340.0, y=0.0)
        nodes = [planner, researcher, developer, analyst, aggregator]
        edges = [
            WorkflowEdge("planner", "researcher"),
            WorkflowEdge("planner", "developer"),
            WorkflowEdge("planner", "analyst"),
            WorkflowEdge("researcher", "aggregator"),
            WorkflowEdge("developer", "aggregator"),
            WorkflowEdge("analyst", "aggregator"),
        ]
        return _template("Parallel Specialists", nodes, edges)
    if name == "planner-workers-reviewer":
        planner = _node("planner", "software-architect", _TEMPLATE_AGENTS[0], "Planner",
                        x=0.0, y=0.0)
        worker1 = _node("worker_1", "python-developer", _TEMPLATE_AGENTS[1], "Worker 1",
                        x=170.0, y=-90.0)
        worker2 = _node("worker_2", "python-developer", _TEMPLATE_AGENTS[2], "Worker 2",
                        x=170.0, y=0.0)
        worker3 = _node("worker_3", "python-developer", _TEMPLATE_AGENTS[3], "Worker 3",
                        x=170.0, y=90.0)
        reviewer = _node("reviewer", "code-reviewer", _TEMPLATE_AGENTS[4], "Reviewer",
                         x=340.0, y=0.0)
        nodes = [planner, worker1, worker2, worker3, reviewer]
        edges = [
            WorkflowEdge("planner", "worker_1"),
            WorkflowEdge("planner", "worker_2"),
            WorkflowEdge("planner", "worker_3"),
            WorkflowEdge("worker_1", "reviewer"),
            WorkflowEdge("worker_2", "reviewer"),
            WorkflowEdge("worker_3", "reviewer"),
        ]
        return _template("Planner / Workers / Reviewer", nodes, edges)
    if name == "research-analysis-writer":
        researcher = _node("researcher", "ai-agent-engineer", _TEMPLATE_AGENTS[0], "Researcher",
                           x=0.0, y=0.0)
        analyst = _node("analyst", "code-reviewer", _TEMPLATE_AGENTS[1], "Analyst",
                        x=150.0, y=0.0)
        writer = _node("writer", "python-developer", _TEMPLATE_AGENTS[2], "Writer",
                       x=300.0, y=0.0)
        nodes = [researcher, analyst, writer]
        edges = [
            WorkflowEdge("researcher", "analyst"),
            WorkflowEdge("analyst", "writer"),
        ]
        return _template("Research / Analysis / Writer", nodes, edges)
    if name == "empty":
        return Workflow(
            id="template-empty", name="Empty Workflow", project="",
            nodes=[], edges=[], entry=[], state={}, settings={"max_iterations": 3},
        )
    return None


def list_templates() -> list[str]:
    return ["sequential", "parallel", "planner-workers-reviewer", "reflection",
            "parallel-specialists", "research-analysis-writer", "supervisor",
            "router", "hierarchical", "empty"]


# ---------------------------------------------------------------- recommendations


def recommend_workflow(repo_root: Path | None = None, n_agents: int = 4) -> dict:
    """Suggest a workflow from the project profile (read-only, never applied).

    Returns ``{workflow, reasons, composition, technologies}``. The suggested
    roles come from :func:`scripts.core.project_profile.suggest_roles` and the
    per-role reasons from ``suggested_role_reasons``; agents are assigned
    round-robin as a *starting point* only (a suggestion, not a coupling).
    """
    from scripts.core.project_profile import (
        analyze_repository,
        suggested_role_reasons,
    )

    n = max(1, min(12, int(n_agents or 1)))
    profile = analyze_repository(repo_root)
    suggested = list(profile.suggested_roles)
    reasons = suggested_role_reasons(profile, repo_root, include_approved=True)

    # Composition: architect + developers (from suggested tech roles) + QA + security.
    tech_roles = [r for r in suggested if r not in ("code-reviewer", "software-architect")]
    composition: list[str] = ["software-architect"]
    for rid in tech_roles[: max(0, n - 3)]:
        composition.append(rid)
    if "qa-engineer" in suggested:
        composition.append("qa-engineer")
    composition.append("code-reviewer")
    # Fill to n with generic developers; then trim to n.
    while len(composition) < n:
        composition.insert(1, "python-developer")
    composition = composition[:n]
    composition = list(dict.fromkeys(composition))  # de-dup, keep order

    nodes: list[WorkflowNode] = []
    for i, rid in enumerate(composition):
        agent = _TEMPLATE_AGENTS[i % len(_TEMPLATE_AGENTS)]
        nodes.append(_node(f"node_{i}", rid, agent, rid.replace("-", " ").title(),
                           x=0.0, y=i * 110.0))
    edges = [WorkflowEdge(f"node_{i - 1}", f"node_{i}") for i in range(1, len(nodes))]

    wf = Workflow(
        id="suggested-workflow",
        name="Suggested Workflow",
        project=str(profile.root),
        nodes=nodes,
        edges=edges,
        entry=["node_0"] if nodes else [],
        settings={"max_iterations": 3},
    )
    return {
        "workflow": wf.to_dict(),
        "reasons": reasons,
        "composition": composition,
        "technologies": list(profile.technologies),
    }

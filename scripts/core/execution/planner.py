"""Execution planner — resolve each workflow node before it executes (Phase 5).

For every node the planner resolves, in order:

    model      → node.model (explicit) else the agent's runtime model
    connection → model_connections.resolver (explicit connection_id wins;
                 implicit resolution degrades to the local OpenCode runtime)
    prompt     → the ONE canonical prompt builder (roles + instruction/profile
                 + workflow state), shared by every execution path
    adapter    → adapter_for(resolved connection); default OpenCode

The planner never touches credentials: it works from connection metadata only
(:class:`~scripts.core.model_connections.resolver.Resolution` and
:class:`~scripts.core.providers.base.ResolvedConnection`). Dry-run reuses the
planner to answer "what would execute?" without executing anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from scripts.core import (
    model_connections,
    opencode_cfg,
    prompt_library,
    runtime_context,
)
from scripts.core.execution.errors import PlanError
from scripts.core.execution.schema import ModelRequest
from scripts.core.providers.base import (
    ResolvedConnection,
    adapter_for,
)
from scripts.core.workflows import WorkflowNode

# ---------------------------------------------------------------- prompt


def _effective_instruction(node: WorkflowNode) -> str:
    """The node's final instruction: its own ``instructions`` when present,
    otherwise the selected Prompt Profile's text (the profile is the *source*;
    the instruction is the *editable* result). Returns ``""`` when neither is
    set or the profile id is unknown."""
    text = node.instructions.strip()
    if text:
        return text
    if node.prompt_profile:
        try:
            return prompt_library.get_prompt(node.prompt_profile).prompt.strip()
        except prompt_library.PromptError:
            return ""
    return ""


def build_node_prompt(node: WorkflowNode, state: dict,
                      repo_root: Path | None = None) -> str:
    """Compose a node's runtime prompt via the shared runtime-context builder.

    This is the **canonical** prompt builder (Phase 5): it now delegates to
    :func:`scripts.core.runtime_context.build_runtime_prompt` so the workflow
    path produces the same ordered context (identity → roles → skills →
    instruction → workflow state → request) as terminal/orchestrator dispatch.
    A node's own ``roles`` override the agent's persistent assignments for this
    run only; its ``skills`` override the agent's assigned skills (inheriting
    them when unset). The instruction is the node's final instruction (its own
    ``instructions``, or the selected Prompt Profile's text when ``instructions``
    is empty).
    """
    # A Home-dispatched command arrives as the run's ``user_prompt`` and is the
    # primary task for every node (the workflow graph, not a single agent,
    # is then the authoritative execution structure).
    user_prompt = (state or {}).get("user_prompt")
    user_request = user_prompt.strip() if isinstance(user_prompt, str) else ""
    workflow = ""
    if state:
        workflow = "## Workflow state\n```json\n" + json.dumps(state, indent=2) + "\n```"
    return runtime_context.build_runtime_prompt(
        node.agent,
        role_ids=list(node.roles) if node.roles else None,
        skill_ids=list(node.skills) if node.skills else None,
        instruction=_effective_instruction(node),
        workflow_context=workflow,
        user_request=user_request,
        repo_root=repo_root,
    )


# ---------------------------------------------------------------- plan


@dataclass(frozen=True)
class NodePlan:
    """The resolved execution plan for one node (safe metadata only)."""

    node_id: str
    model: str
    prompt: str
    resolution: object | None = None          # model_connections.Resolution (metadata)
    connection: ResolvedConnection = field(default_factory=ResolvedConnection)
    adapter_id: str = "opencode"
    provider: str = "opencode"
    connection_error: str = ""                # implicit resolution note (safe)
    request: ModelRequest | None = None

    def to_dict(self) -> dict:
        """Dry-run / preview metadata — never contains credentials."""
        return {
            "node_id": self.node_id,
            "model": self.model,
            "connection_id": self.connection.connection_id,
            "provider": self.provider,
            "adapter": self.adapter_id,
            "prompt_profile": str(self.request.metadata.get("prompt_profile") or "")
            if self.request else "",
            "task": self.request.metadata.get("task") if self.request else None,
            "prompt_len": len(self.prompt) if self.prompt else 0,
            "connection_error": self.connection_error,
        }


def plan_node(node: WorkflowNode, state: dict,
              repo_root: Path | None = None,
              execution_id: str | None = None) -> NodePlan:
    """Resolve one node into an executable plan.

    * Explicit ``node.model`` always wins; otherwise the agent's configured
      runtime model is used (opencode.json, via ``opencode_cfg.resolve_model``).
    * Explicit ``node.connection_id`` always wins — a missing/invalid explicit
      connection raises :class:`PlanError` (execution fails loudly, never
      silently substitutes another connection).
    * Without an explicit connection, resolution degrades to the local OpenCode
      runtime when the model's provider has no configured connection — the
      same behavior as today (opencode handles its own auth/fallback). The
      degradation is recorded as safe plan metadata.
    """
    model = (node.model or "").strip() or (opencode_cfg.resolve_model(
        node.agent, repo_root) or "")
    prompt = build_node_prompt(node, state, repo_root)

    resolution = None
    connection_error = ""
    try:
        resolution = model_connections.resolve(
            model=model or None, connection_id=(node.connection_id or "").strip() or None)
    except model_connections.ConnectionError as exc:
        if (node.connection_id or "").strip():
            # Explicit selection: authoritative, never silently replaced.
            raise PlanError(str(exc)) from exc
        # Implicit: degrade to the local runtime (opencode default).
        connection_error = str(exc)
        resolution = None

    if resolution is not None:
        connection = ResolvedConnection(
            connection_id=resolution.connection_id or "",
            provider=resolution.provider or "",
            endpoint=resolution.endpoint,
            deployment=resolution.deployment,
            local=resolution.local,
            source=resolution.source,
        )
        provider = resolution.provider or "opencode"
    else:
        connection = ResolvedConnection(local=True, source="local")
        provider = "opencode"

    adapter = adapter_for(resolution)
    request = ModelRequest(
        model=model,
        prompt=prompt,
        stream=False,
        metadata={
            "workflow_id": str(getattr(node, "_workflow_id", "") or ""),
            "node_id": node.id,
            "execution_id": execution_id or "",
            "agent": node.agent,
            "prompt_profile": node.prompt_profile,
            "task": node.task,
        },
    )
    return NodePlan(
        node_id=node.id,
        model=model,
        prompt=prompt,
        resolution=resolution,
        connection=connection,
        adapter_id=adapter.provider_id,
        provider=provider,
        connection_error=connection_error,
        request=request,
    )

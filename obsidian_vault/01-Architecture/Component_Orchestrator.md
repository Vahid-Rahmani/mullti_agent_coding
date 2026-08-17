---
type: architecture
status: active
owner: architect
created: 2026-08-17
updated: 2026-08-17
related: [System_Architecture, Component_VaultBridge, Component_ContextResolver, Component_RunHub, Component_AgentSpecs, Tasks_Home, Agents_Home]
---

# Component_Orchestrator

> Controlled execution of task nodes through the existing agent runtime.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Coordinates executable task nodes from `03-Tasks/`: validates readiness,
resolves the assigned roster agent, builds bounded runtime context, dispatches
through the shared OpenCode command boundary, and persists the result back to
the task node.

## Source (verified)

- `scripts/core/orchestrator.py` — task commands, transitions, locks, dispatch,
  Agent Report parsing, and result persistence
- `scripts/web_ui/routes.py` — Dashboard task endpoints that invoke the real
  Orchestrator CLI rather than a second task engine

## Responsibilities

- Enforce the task lifecycle and dispatch only `ready` nodes
- Keep execution a dry-run unless the operator supplies explicit `--yes`
- Acquire and release a per-task lock to prevent concurrent duplicate runs
- Resolve the assigned agent and bounded linked context
- Compose the canonical runtime prompt and run the shared OpenCode command
- Parse structured `## Agent Report` output and persist execution status/logs
- Detect workspace scope drift and report unsafe or incomplete outcomes

## Dependencies

- [[Component_VaultBridge]] — all task-node reads, managed writes, backups,
  relationship resolution, and change logging
- [[Component_ContextResolver]] — deterministic bounded context packages
- [[Component_RunHub]] — shared OpenCode executable and command helpers
- [[Component_AgentSpecs]] — roster identity and runtime agent resolution
- `scripts/core/runtime_context.py`, `scripts/core/roles.py`, and
  `scripts/core/opencode_cfg.py` — prompt, role, and runtime-model composition

## Operational Status

Active. The CLI supports `list`, `show`, `set-status`, `dispatch`, `report`,
and `context`. Real execution requires `--yes`; task outcomes and Agent Reports
are inspectable in the task node and Dashboard API.

## Known Limitations

- Executes one Vault task at a time per task lock; it is not a shared queue
- Depends on the external `opencode` CLI and the configured model/provider
- This is the Vault **task Orchestrator**, not the separate workflow graph
  scheduler in `scripts/core/workflow_engine.py`

## Input / Output

- **Input:** a task node, its assigned agent/component/dependencies, and
  explicit execution authorization
- **Output:** OpenCode output plus persisted task status, Execution Log, and
  structured Agent Report

## Related Agents / Tasks / Workflows

- Any agent under [[Agents_Home]] may be selected dynamically by task
  frontmatter; the component is not coupled to one identity
- Task lifecycle and dispatchable work are indexed by [[Tasks_Home]]
- Workflow graph execution remains a separate subsystem

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_VaultBridge]], [[Component_ContextResolver]], [[Component_RunHub]], [[Component_AgentSpecs]], [[Tasks_Home]], [[Agents_Home]]

---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-11
related: [System_Architecture, Component_Terminal, Component_AgentSpecs, Component_StateTracker]
---

# Component_RunHub

> Thread-safe multi-agent execution engine.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Spawns one worker thread per target agent; each thread streams `opencode run`
output into per-tag buffers. Owns all live-run telemetry (status, progress,
token usage, prompts, events) and the abort/terminate machinery.

## Source (verified)

- `scripts/core/run_hub.py` — `RunHub` class + module-level `HUB` singleton
- Helper functions: `prune_prompt`, `_build_run_command`, `_opencode_command`

## Responsibilities

- Plain dispatch: `opencode run --agent <a> --auto [-m <model>] "<prompt>"`
- Per-agent status transitions (idle → thinking → active → idle/error)
- Progress + token estimation via `scripts/core/progress.py`
- Terminate single agent / all agents; record restarts via [[Component_StateTracker]]
- Aggregate weighted master progress for the loading bar

## Dependencies

- [[Component_AgentSpecs]] — roster; runtime models resolved from `opencode.json`
- `scripts/core/roles.py` + `roles.json` — reusable roles composed onto an
  agent at dispatch (many-to-many, model-independent)
- `scripts/core/progress.py` — `_estimate_token_percent`, `_weighted_progress`
- [[Component_StateTracker]] — `STATE.record_run/finish/restart`
- `opencode` CLI on PATH (external runtime)

## Input / Output

- **Input:** prompt string, target agent tags, enabled-agent set
- **Output:** event stream (`seq`, `tag`, `kind`, `text`) + per-tag buffers consumed by [[Component_Terminal]]

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_Terminal]], [[Component_AgentSpecs]], [[Component_StateTracker]]

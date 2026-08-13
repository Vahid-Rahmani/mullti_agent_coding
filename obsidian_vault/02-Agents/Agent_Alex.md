---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agents_Home, System_Core, System_Architecture, Component_RunHub, Component_AgentSpecs, Component_Terminal]
---

# Agent_Alex

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Identity

- **Tag:** M2
- **Agent key:** `alex`
- **Name:** Alex
- **Model:** runtime-configured in `opencode.json` (Settings / BYOK)
- **Mode:** all

## Purpose

Control-plane agent: a plain agent — **identity only** — with no specialized
role prompt; its model and role are resolved at runtime (model from
`opencode.json`, role from `roles.json`).

## Current Responsibilities

- Execute dispatched prompts via
  `opencode run --agent alex --auto -m <runtime model> "<prompt>"`
- Run from the [[Component_Terminal]] tab (M2) or the inbox worker
  ([[Component_Launchers]], `_inbox/alex.task`)
- Stream output back to the terminal buffer / `_logs/alex.log`
- Report run completion to [[Component_StateTracker]] (`state.md`)

## Input

- Prompt string typed on the M2 tab (or MASTER, which fans out to all agents)
- Task file dropped at `_inbox/alex.task`

## Output

- Streamed text output → per-tag buffer (M2 console / MASTER console)
- Log lines appended to `_logs/alex.log`
- `state.md` completion record (`m2: ok` / `m2: failed`)

## Dependencies

- `opencode` CLI on PATH
- [[Component_RunHub]] — dispatch + telemetry
- [[Component_AgentSpecs]] — identity; runtime model resolved from `opencode.json`
- Model-fallback chain: `[opencode/big-pickle, opencode/deepseek-v4-flash-free, ollama/qwen2.5-coder:7b]`

## Current Status

`active` — fully integrated with Terminal, RunHub, AgentSpecs, and launchers.

## Related Tasks

- [[Tasks_Home]] — no individual task nodes exist yet

## Related Architecture

- [[System_Core]], [[System_Architecture]]
- [[Component_Terminal]], [[Component_RunHub]], [[Component_AgentSpecs]], [[Component_Launchers]]

## Links

- ↑ Parent: [[Agents_Home]]
- ↔ Related: [[System_Core]], [[System_Architecture]], [[Agent_Matthew]], [[Agent_Sarah]], [[Agent_David]], [[Agent_Elena]], [[Agent_Max]], [[Agent_Chloe]]

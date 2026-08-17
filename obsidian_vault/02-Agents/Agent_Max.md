---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agents_Home, System_Core, System_Architecture, Component_RunHub, Component_AgentSpecs, Component_Terminal]
---

# Agent_Max

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Identity

- **Tag:** M6
- **Agent key:** `max`
- **Name:** Max
- **Model:** runtime-configured in `opencode.json` (Settings / BYOK)
- **Mode:** all

## Purpose

Control-plane agent: a plain agent — **identity only** — with no specialized
role prompt; its model and role are resolved at runtime (model from
`opencode.json`, role from `roles.json`).

## Current Responsibilities

- Execute dispatched prompts via
  `opencode run --agent max --auto -m <runtime model> "<prompt>"`
- Run from the [[Component_Terminal]] tab (M6) or the inbox worker
  ([[Component_Launchers]], `_inbox/max.task`)
- Stream output back to the terminal buffer / `_logs/max.log`
- Report run completion to [[Component_StateTracker]] (`state.md`)

## Input

- Prompt string typed on the M6 tab (or MASTER, which fans out to all agents)
- Task file dropped at `_inbox/max.task`

## Output

- Streamed text output → per-tag buffer (M6 console / MASTER console)
- Log lines appended to `_logs/max.log`
- `state.md` completion record (`m6: ok` / `m6: failed`)

## Dependencies

- `opencode` CLI on PATH
- [[Component_RunHub]] — dispatch + telemetry
- [[Component_AgentSpecs]] — identity; runtime model resolved from `opencode.json`
- Model-fallback chain: `[opencode/big-pickle, opencode/deepseek-v4-flash-free, ollama/qwen2.5-coder:7b]`

## Current Status

`active` — fully integrated with Terminal, RunHub, AgentSpecs, and launchers.

## Related Tasks

- [[Tasks_Home]] — seeded task nodes listed in [[Task_Backlog]]

## Related Architecture

- [[System_Core]], [[System_Architecture]]
- [[Component_Terminal]], [[Component_RunHub]], [[Component_AgentSpecs]], [[Component_Launchers]]

## Links

- ↑ Parent: [[Agents_Home]]
- ↔ Related: [[System_Core]], [[System_Architecture]], [[Agent_Matthew]], [[Agent_Alex]], [[Agent_Sarah]], [[Agent_David]], [[Agent_Elena]], [[Agent_Chloe]]

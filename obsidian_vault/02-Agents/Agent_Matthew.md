---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agents_Home, System_Core, System_Architecture, Component_RunHub, Component_AgentSpecs, Component_Terminal]
---

# Agent_Matthew

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Identity

- **Tag:** M1
- **Agent key:** `matthew`
- **Name:** Matthew
- **Model:** `opencode/deepseek-v4-flash-free`
- **Mode:** all

## Purpose

Default control-plane agent (also the `default_agent` in `opencode.json`).
At baseline-zero it is a plain agent — identity + model only, with no
specialized role prompt.

## Current Responsibilities

- Execute dispatched coding/analysis prompts via
  `opencode run --agent matthew --auto -m opencode/deepseek-v4-flash-free "<prompt>"`
- Run either from the [[Component_Terminal]] tab (M1) or the inbox worker
  ([[Component_Launchers]], `_inbox/matthew.task`)
- Stream output back to the terminal buffer / `_logs/matthew.log`
- Report run completion to [[Component_StateTracker]] (`state.md`)

## Input

- Prompt string typed on the M1 tab (or MASTER, which fans out to all agents)
- Task file dropped at `_inbox/matthew.task`

## Output

- Streamed text output → per-tag buffer (M1 console / MASTER console)
- Log lines appended to `_logs/matthew.log`
- `state.md` completion record (`m1: ok` / `m1: failed`)

## Dependencies

- `opencode` CLI on PATH
- [[Component_RunHub]] — dispatch + telemetry
- [[Component_AgentSpecs]] — configured model (`deepseek-v4-flash-free`)
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
- ↔ Related: [[System_Core]], [[System_Architecture]], [[Agent_Alex]], [[Agent_Sarah]], [[Agent_David]], [[Agent_Elena]], [[Agent_Max]], [[Agent_Chloe]]

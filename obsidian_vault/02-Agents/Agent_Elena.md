---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agents_Home, System_Core, System_Architecture, Component_RunHub, Component_AgentSpecs, Component_Terminal]
---

# Agent_Elena

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Identity

- **Tag:** M5
- **Agent key:** `elena`
- **Name:** Elena
- **Model:** `opencode/ling-3.0-tiny-free`
- **Mode:** all

## Purpose

Control-plane agent at baseline-zero: a plain agent — identity + model only,
with no specialized role prompt. Uses the lightweight `ling-3.0-tiny-free`
model (fast/small model in the roster).

## Current Responsibilities

- Execute dispatched prompts via
  `opencode run --agent elena --auto -m opencode/ling-3.0-tiny-free "<prompt>"`
- Run from the [[Component_Terminal]] tab (M5) or the inbox worker
  ([[Component_Launchers]], `_inbox/elena.task`)
- Stream output back to the terminal buffer / `_logs/elena.log`
- Report run completion to [[Component_StateTracker]] (`state.md`)

## Input

- Prompt string typed on the M5 tab (or MASTER, which fans out to all agents)
- Task file dropped at `_inbox/elena.task`

## Output

- Streamed text output → per-tag buffer (M5 console / MASTER console)
- Log lines appended to `_logs/elena.log`
- `state.md` completion record (`m5: ok` / `m5: failed`)

## Dependencies

- `opencode` CLI on PATH
- [[Component_RunHub]] — dispatch + telemetry
- [[Component_AgentSpecs]] — configured model (`ling-3.0-tiny-free`)
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
- ↔ Related: [[System_Core]], [[System_Architecture]], [[Agent_Matthew]], [[Agent_Alex]], [[Agent_Sarah]], [[Agent_David]], [[Agent_Max]], [[Agent_Chloe]]

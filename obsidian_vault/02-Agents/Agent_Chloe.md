---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agents_Home, System_Core, System_Architecture, Component_RunHub, Component_AgentSpecs, Component_Terminal]
---

# Agent_Chloe

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Identity

- **Tag:** M7
- **Agent key:** `chloe`
- **Name:** Chloe
- **Model:** `opencode/ling-3.0-tiny-free`
- **Mode:** all

## Purpose

Control-plane agent at baseline-zero: a plain agent — identity + model only,
with no specialized role prompt. Uses the lightweight `ling-3.0-tiny-free`
model (fast/small model in the roster).

## Current Responsibilities

- Execute dispatched prompts via
  `opencode run --agent chloe --auto -m opencode/ling-3.0-tiny-free "<prompt>"`
- Run from the [[Component_Terminal]] tab (M7) or the inbox worker
  ([[Component_Launchers]], `_inbox/chloe.task`)
- Stream output back to the terminal buffer / `_logs/chloe.log`
- Report run completion to [[Component_StateTracker]] (`state.md`)

## Input

- Prompt string typed on the M7 tab (or MASTER, which fans out to all agents)
- Task file dropped at `_inbox/chloe.task`

## Output

- Streamed text output → per-tag buffer (M7 console / MASTER console)
- Log lines appended to `_logs/chloe.log`
- `state.md` completion record (`m7: ok` / `m7: failed`)

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
- ↔ Related: [[System_Core]], [[System_Architecture]], [[Agent_Matthew]], [[Agent_Alex]], [[Agent_Sarah]], [[Agent_David]], [[Agent_Elena]], [[Agent_Max]]

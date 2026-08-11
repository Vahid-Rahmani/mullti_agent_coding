---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-11
related: [Architecture_Home]
---

# Architecture_Overview

> Seed node summarizing the current system: the baseline-zero control plane.

**Type:** architecture · **Status:** active · **Owner:** architect

---

## What This System Is

A **multi-agent coding control plane** at "baseline-zero": seven plain agents
(identity + model only) that dispatch coding tasks through the opencode CLI.
No roles, no operational modes, no external integrations.

## Core Components

| Component | Location | Responsibility |
|---|---|---|
| ZOVA Retro Terminal | `scripts/terminal_app.py` → `scripts/ui/` | Full-screen prompt_toolkit UI (tabs M1–M7 + MASTER) |
| Run Hub | `scripts/core/run_hub.py` | Thread-safe dispatch: one thread per agent → `opencode run` |
| Agent Specs | `scripts/core/agents/` | One `AgentSpec` module per agent; `registry.py` derives roster |
| State Tracker | `scripts/core/state_tracker.py` | Atomic read/write of `state.md` |
| Inbox Workers | `scripts/run_agent_worker.ps1/.sh` | Poll `_inbox/<agent>.task`, run, log, archive to `_inbox/done/` |
| Launchers | `launch_agents.bat`, `launch_terminal.bat` | 7-window inbox launcher + terminal launcher |

## Agent Roster (M1–M7)

| Tag | Agent | Model |
|---|---|---|
| M1 | `matthew` | opencode/deepseek-v4-flash-free |
| M2 | `alex` | opencode/deepseek-v4-flash-free |
| M3 | `sarah` | opencode/deepseek-v4-flash-free |
| M4 | `david` | opencode/big-pickle |
| M5 | `elena` | opencode/ling-3.0-tiny-free |
| M6 | `max` | opencode/deepseek-v4-flash-free |
| M7 | `chloe` | opencode/ling-3.0-tiny-free |

## References

- ↑ Parent: [[Architecture_Home]]
- ↔ Related: [[Agents_Home]], [[Documentation_Home]]
- Repo: `docs/architecture/Architecture.md`, `AGENTS.md`, `README.md`

## Future Work

Detailed component designs, data flows, and integration contracts will be added
here as the system evolves past baseline-zero.

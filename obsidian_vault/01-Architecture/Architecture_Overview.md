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

A **multi-agent coding control plane**: seven plain agents (**identity only**)
that dispatch coding tasks through the opencode CLI. Each agent's model is
resolved at runtime from `opencode.json` (Settings / BYOK), and reusable roles
are assigned via `roles.json` — so identity, model, and role are never
permanently coupled.

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
| M1 | `matthew` | runtime-configured (opencode.json) |
| M2 | `alex` | runtime-configured (opencode.json) |
| M3 | `sarah` | runtime-configured (opencode.json) |
| M4 | `david` | runtime-configured (opencode.json) |
| M5 | `elena` | runtime-configured (opencode.json) |
| M6 | `max` | runtime-configured (opencode.json) |
| M7 | `chloe` | runtime-configured (opencode.json) |

> Models are not part of agent identity: any agent can run on any
> user-selected model via the Settings / BYOK layer.

## References

- ↑ Parent: [[Architecture_Home]]
- ↔ Related: [[Agents_Home]], [[Documentation_Home]]
- Repo: `docs/architecture/Architecture.md`, `AGENTS.md`, `README.md`

## Future Work

Detailed component designs, data flows, and integration contracts will be added
here as the system evolves past baseline-zero.

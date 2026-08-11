---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-11
related: [System_Architecture, Component_AgentSpecs]
---

# Component_Launchers

> Startup and inbox-driven execution launchers for the control plane.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Two entry paths into the system: (1) a 7-window inbox launcher that runs each
agent side by side polling its own task inbox, and (2) a launcher for the ZOVA
retro terminal. Both resolve agent models from [[Component_AgentSpecs]].

## Source (verified)

- `launch_agents.bat` — 7-window launcher (reads roster via
  `python -m scripts.core.agents roster`; `--smoke` / `--dry` / `--help`)
- `launch_terminal.bat` — terminal launcher (`--workspace` / `--smoke`)
- `scripts/run_agent_worker.ps1` / `.sh` — inbox-polling workers

## Responsibilities

- Launch 7 PowerShell windows in a 4×2 grid (M1–M4 top, M5–M7 bottom)
- Poll `_inbox/<agent>.task`, run `opencode run --agent <a> --auto -m <m> "<task>"`,
  append output to `_logs/<agent>.log`, move consumed tasks to `_inbox/done/`
- Optional `ZOVA_ALLOW_INSECURE_TLS=1` → `NODE_TLS_REJECT_UNAUTHORIZED=0` (opt-in)

## Dependencies

- [[Component_AgentSpecs]] — `roster` / `model` CLI for roster + model resolution
- `opencode` CLI, PowerShell / Git Bash, Python on PATH

## Input / Output

- **Input:** task files dropped into `_inbox/<agent>.task`
- **Output:** per-agent logs in `_logs/`, archived tasks in `_inbox/done/`

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_AgentSpecs]]

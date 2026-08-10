# MultiAgentCoding — Control Plane

A self-evolving multi-agent coding system. This repository is the **control
plane** that defines the agents, skills, configuration, and memory used to drive
software projects. It ships two ways to interact with the agent swarm: a
retro-CRT **ZOVA terminal** and a 7-window inbox launcher.

---

## Overview

The control plane defines seven humanified specialists—Matthew, Alex, Sarah,
David, Elena, Max, and Chloe—that collaborate to build software. Each has a
distinct operational role, model assignment, and permission scope configured in
[`opencode.json`](opencode.json).

| Agent | Role | Model |
|---|---|---|
| `matthew` | Matthew — architecture + master coordination (read-only) | opencode/deepseek-v4-flash-free |
| `alex` | Alex — backend, APIs, Python logic, and data handling | opencode/deepseek-v4-flash-free |
| `sarah` | Sarah — TUI, frontend, UX, and rendering | opencode/deepseek-v4-flash-free |
| `david` | David — QA, TDD, tests, and debugging | opencode/big-pickle |
| `elena` | Elena — code quality and security audit (read-only) | opencode/ling-3.0-tiny-free |
| `max` | Max — DevOps, automation, and environment stability | opencode/deepseek-v4-flash-free |
| `chloe` | Chloe — documentation and Obsidian knowledge audit (read-only) | opencode/ling-3.0-tiny-free |

All agents use **free** models (no paid credits required). See
[`AGENTS.md`](AGENTS.md) for full role, workflow, and fallback-policy details.

---

## Quick Start

### 1. ZOVA Retro Terminal (recommended)

The interactive terminal UI. Full-screen retro-CRT styling on a solid black
background: a bold pixel-art **ZOVA** banner, a live directory status
indicator, a **tab bar** (MASTER + one tab per agent), a model status bar, a
per-tab scrollable console, and a rounded prompt box at the bottom for typing
coding tasks or slash commands.

**Tabbed agent workspace** — the seven agents each get their own dedicated
tab (M1 Matthew … M7 Chloe) inside the single unified window, so
they operate independently. `F1`–`F7` select an agent tab, `F8` selects
MASTER (all agents), `Ctrl+T` cycles tabs, or use `/tab <tag>`. A task typed
on an agent tab dispatches to that agent only; on the MASTER tab it goes to
all agents (or the `/agents` filter). Each tab has its own console showing
only that agent's output.

**Strict color scheme** — the UI uses exactly four colors and nothing else:
white for regular text, orange for important details & keywords, grey for
selected text & background highlights, and neon-green (phosphor green) for
special highlights (banner, status notifications) on the solid black background.

```bash
python scripts/terminal_app.py     # full-screen retro terminal
launch_terminal.bat                # same, in a new window
python scripts/terminal_app.py --smoke   # headless build check
```

**Features:**
- **Pixel-art ZOVA banner** — block-glyph banner in bold neon green.
- **Directory indicator** — `▶ DIR: <path>` under the banner; change it with
  `/cd <path>` so agents work in any folder.
- **Agent tabs** — live M1–M7 status per tab (● idle / ◐ thinking / ● active /
  ✕ error); the active tab is bracket-highlighted in neon, inactive tabs
  render grey, busy/error states orange.
- **Model status bar** — active tab / model / mode / dispatch target /
  running count, embedded in the rounded prompt box's top border.
- **Rounded prompt box** — Enter submits, Ctrl+J inserts a newline,
  Ctrl+C clears the input (press again to quit), PageUp/PageDown scrolls the
  active tab's console, `/` starts a command with tab completion.
- **Workspace-aware** — agents run `opencode run --agent <agent> --auto
  "<prompt>"` with the current workspace as their working directory.
  `--auto` auto-approves tool permissions (`opencode run` has no `--yes`/`-y`).

**Slash commands:** `/tab [tag]`, `/help`, `/cd <path>`, `/model [name]`,
`/mode [name]`, `/agents [tags]`, `/status`, `/clear`, `/stop`, `/swarm`,
`/proposals`, `/evolve <prompt>`, `/quit`.

### 2. 7-Window Inbox Launcher

Runs the seven roles side by side, each listening for tasks in its own inbox,
with **Dynamic Swarm Role-Swapping & Peer-Assistance** built in.

```bat
launch_agents.bat            # launch all 7 agent windows (swarm mode ON)
launch_agents.bat --smoke    # seed SMOKE tasks and run once
launch_agents.bat --dry      # print the launch commands only
launch_agents.bat --no-swarm # disable helper rotation
launch_agents.bat --stale N  # treat a peer's task as lagging after N s (default 20)
```

Drop a single-line task into `_inbox/<agent>.task` (e.g. `_inbox/alex.task`).
The agent's window polls the inbox, runs the task, appends output to
`_logs/<agent>.log`, and moves the consumed task to `_inbox/done/`.

**Swarm protocol** (implemented in `scripts/swarm.py` + `scripts/run_agent_worker.ps1`):

1. **Role rotation on completion** — after finishing its own task, an idle
   worker scans `_inbox/` for *lagging peers* (tasks unclaimed for
   `--stale N` seconds). It atomically claims one and executes it with the
   peer's own agent identity (`--agent <peer>`), logging into the peer's
   `_logs/<peer>.log`.
2. **Dynamic tab renaming** — the window title updates in real time to show
   the cooperative role, e.g. `M3 - Sarah` → `M3-Helper->M1`, and the live
   role is persisted per slot in `_logs/swarm/m<slot>.json` so any UI can
   reflect it.
3. **Inter-agent learning & feedback loop** — every run (own or assisted)
   appends a JSONL record to `_logs/swarm_feedback.jsonl` (who, mode, ok,
   duration). Before each run the worker injects a "swarm brief" built from
   recent records + live helpers into the prompt, so agents share context
   across execution cycles.

Disable rotation with `--no-swarm`; skip the brief injection by passing
`-NoBrief` to `scripts/run_agent_worker.ps1` directly.

---

## Installing the `myagent` Command (Windows)

Make the ZOVA terminal globally runnable from any folder:

1. Find the Python Scripts directory:
   ```bat
   python -c "import sys; print(sys.prefix + '\\Scripts')"
   ```
2. Create `myagent.bat` in that directory with:
   ```bat
   @echo off
   python "C:\absolute\path\to\scripts\terminal_app.py" %*
   ```
3. Verify it is recognized:
   ```bat
   where myagent
   ```

Now `myagent` launches the retro terminal targeting the folder you run it from.

---

## Project Layout

```
.
├── AGENTS.md              # Agent roles, workflow, fallback policy, conventions
├── opencode.json          # Agent definitions, models, providers, permissions
├── launch_agents.bat      # 7-window inbox launcher (swarm mode ON)
├── launch_terminal.bat    # ZOVA retro terminal launcher
├── scripts/
│   ├── terminal_app.py    # ZOVA retro terminal (full-screen interactive UI)
│   ├── swarm.py           # Swarm coordinator (role rotation, feedback, briefs)
│   ├── run_agent_worker.ps1  # Inbox-polling worker (Windows, 7-window launcher)
│   ├── run_agent_worker.sh   # Inbox-polling worker (Git Bash)
│   ├── intent_router.py   # Intent classification/routing for the swarm
│   └── self_evolve.py     # Self-evolution engine (verify + restart marker)
├── knowledge/             # Swarm memory (ADRs, lessons, metrics)
├── .opencode/             # opencode plugins/config (e.g. model fallback)
└── .vscode/               # VS Code tasks (Launch All Agents / ZOVA Retro Terminal)
```

---

## Conventions

- Never commit secrets. Keys live only in `~/.local/share/opencode/auth.json`.
- Never commit `knowledge/index.jsonl` or anything under `_logs/`.
- Consult `knowledge/` before planning or reviewing.
- Commits are small and single-purpose; branch pattern `feature/{agent}-{task}`.

---

## Memory & Evolution

Architecture decisions and lessons learned are appended to `knowledge/adr/` and
`knowledge/lessons/`. After a milestone, run the retro to summarize the session,
prune stale memory, and update these conventions.

See [`AGENTS.md`](AGENTS.md) for the complete control-plane documentation.

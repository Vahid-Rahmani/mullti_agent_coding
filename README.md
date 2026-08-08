# MultiAgentCoding — Control Plane

A self-evolving multi-agent coding system. This repository is the **control
plane** that defines the agents, skills, configuration, and memory used to drive
software projects. It ships two ways to interact with the agent swarm: a
7-window inbox launcher and a single-window AI Agent Workspace GUI.

---

## Overview

The control plane defines seven specialized agents that collaborate to build
software. Each agent has a distinct role, model assignment, and permission
scope, all configured in [`opencode.json`](opencode.json).

| Agent | Role | Model |
|---|---|---|
| `system-architect` | System architecture + design approval (read-only) | opencode/deepseek-v4-flash-free |
| `analyst` | Requirements analysis (read-only) | opencode/big-pickle |
| `planner` | PLAN.md + TASKS.json (read-only) | opencode/big-pickle |
| `backend-dev` | Backend implementation | opencode/deepseek-v4-flash-free |
| `frontend-dev` | Frontend implementation | opencode/deepseek-v4-flash-free |
| `tester` | Test authoring + execution | opencode/big-pickle |
| `reviewer` | Code review, approve/reject (read-only) | opencode/ling-3.0-tiny-free |

All agents use **free** models (no paid credits required). See
[`AGENTS.md`](AGENTS.md) for full role, workflow, and fallback-policy details.

---

## Quick Start

### 1. AI Agent Workspace GUI (recommended)

A single-window dashboard with a workspace header, live agent status badges,
tabbed per-agent consoles, and an interactive command bar.

```bash
python scripts/unified_app.py
```

Or, from anywhere on Windows (after setup):

```bash
myagent
```

**Features:**
- **Workspace header** — shows the current target path (`📂 Workspace: …`) with a
  **Change Directory…** button so agents work in whatever folder you choose.
- **Status dashboard** — live badges for M1–M7 (⚪ Idle / 🟡 Thinking / 🟢 Active /
  🔴 Error); click a badge to jump to that agent's tab.
- **Tabbed consoles** — a `💬 Master Console` plus one tab per agent; each agent's
  output (ANSI-stripped) streams into its own tab.
- **Control bar** — prompt entry + **RUN COMMAND**, **CLEAR LOGS**, an
  **Auto-scroll** toggle, and quick-action shortcuts (Analyze / Plan / Implement /
  Test / Review).
- **Workspace-aware** — agents run `opencode run --agent <agent> --auto "<prompt>"`
  with the current workspace as their working directory.

> `--auto` auto-approves tool permissions (bash/file ops) so agents can act
> without interactive approval. (`opencode run` has no `--yes`/`-y` flag.)

### 2. Web UI (browser-based, Dyad-style)

A modern browser-based workspace with an icon sidebar, center chat workplane,
live Code + Terminal canvas, and a ⚙ API & Models manager.

```bash
python scripts/web_app.py          # starts server, opens the browser
launch_web.bat                     # same, Windows launcher
python scripts/web_app.py --no-browser --port 8501   # headless
```

**Features:**
- **Left icon sidebar** — collapsible navigation for Master Console, M1–M7, ⚙ Settings.
- **Center workplane** — chat interface per tab, cascading Model/Mode dropdowns,
  collapsible "Thoughts & process" accordions, quick-action pills (Plan / Build / Review).
- **Live Canvas (right)** — real-time Code output (syntax-highlighted) and Terminal logs.
- **⚙ API & Models Manager** — add/edit/delete providers and models in
  `opencode.json` (atomic writes, `.bak` backup). Keys stay in
  `~/.local/share/opencode/auth.json` — never stored here.

### 7-Window Inbox Launcher

Runs the seven roles side by side, each listening for tasks in its own inbox.

```bat
launch_agents.bat            # launch all 7 agent windows
launch_agents.bat --smoke    # seed SMOKE tasks and run once
launch_agents.bat --dry      # print the launch commands only
```

Drop a single-line task into `_inbox/<agent>.task` (e.g. `_inbox/analyst.task`).
The agent's window polls the inbox, runs the task, appends output to
`_logs/<agent>.log`, and moves the consumed task to `_inbox/done/`.

---

## Installing the `myagent` Command (Windows)

Make the workspace GUI globally runnable from any folder:

1. Find the Python Scripts directory:
   ```bat
   python -c "import sys; print(sys.prefix + '\\Scripts')"
   ```
2. Create `myagent.bat` in that directory with:
   ```bat
   @echo off
   python "C:\absolute\path\to\scripts\unified_app.py" %*
   ```
3. Verify it is recognized:
   ```bat
   where myagent
   ```

Now `myagent` launches the workspace GUI targeting the folder you run it from.

---

## Project Layout

```
.
├── AGENTS.md              # Agent roles, workflow, fallback policy, conventions
├── opencode.json          # Agent definitions, models, providers, permissions
├── launch_agents.bat      # 7-window inbox launcher
├── scripts/
│   ├── unified_app.py     # AI Agent Workspace GUI (single window)
│   └── run_agent_worker.ps1  # Inbox-polling worker for the 7-window launcher
├── knowledge/             # Swarm memory (ADRs, lessons, metrics)
├── .opencode/             # opencode plugins/config (e.g. model fallback)
└── .vscode/               # VS Code tasks (Launch All Agents)
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

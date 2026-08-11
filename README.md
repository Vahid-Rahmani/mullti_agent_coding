# MultiAgentCoding — Control Plane

A multi-agent coding system. This repository is the **control plane** that
defines the agents, configuration, and memory used to drive software projects.
It ships two ways to interact with the agents: a retro-CRT **ZOVA terminal**
and a 7-window inbox launcher.

> **Baseline-zero:** agents are plain (identity + model only), dispatch is
> plain, and all external integrations (Obsidian archivist, analyzer, swarm,
> self-evolve) have been removed. This is an unopinionated slate for
> step-by-step rebuilding.

---

## Overview

The control plane defines seven agents — Matthew, Alex, Sarah, David, Elena,
Max, and Chloe — configured in [`opencode.json`](opencode.json). Each has a
model assignment and an explicit fallback chain.

| Agent | Model |
|---|---|
| `matthew` | opencode/deepseek-v4-flash-free |
| `alex` | opencode/deepseek-v4-flash-free |
| `sarah` | opencode/deepseek-v4-flash-free |
| `david` | opencode/big-pickle |
| `elena` | opencode/ling-3.0-tiny-free |
| `max` | opencode/deepseek-v4-flash-free |
| `chloe` | opencode/ling-3.0-tiny-free |

All agents use **free** models (no paid credits required). See
[`AGENTS.md`](AGENTS.md) for workflow and fallback-policy details.

---

## Quick Start

### 1. ZOVA Retro Terminal (recommended)

The interactive terminal UI. Full-screen retro-CRT styling on a solid black
background: a bold pixel-art **ZOVA** banner, a live directory status
indicator, a **tab bar** (MASTER + one tab per agent), a model status bar, a
per-tab scrollable console, and a rounded prompt box at the bottom for typing
coding tasks or slash commands.

**Tabbed agent workspace** — the seven agents each get their own dedicated
tab (M1 Matthew … M7 Chloe) inside the single unified window. `F1`–`F7` select
an agent tab, `F8` selects MASTER (all agents), `Ctrl+T` cycles tabs, or use
`/tab <tag>`. A task typed on an agent tab dispatches to that agent only; on
the MASTER tab it goes to all agents. Each tab has its own console showing
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
- **Model status bar** — active tab / model / dispatch target / running count,
  embedded in the rounded prompt box's top border.
- **Rounded prompt box** — Enter submits, Ctrl+J inserts a newline,
  Ctrl+C clears the input (press again to quit), PageUp/PageDown scrolls the
  active tab's console, `/` starts a command with tab completion.
- **Workspace-aware** — agents run `opencode run --agent <agent> --auto
  -m <model> "<prompt>"` with the current workspace as their working
  directory. `--auto` auto-approves tool permissions (`opencode run` has no
  `--yes`/`-y`).

**Slash commands:** `/tab [tag]`, `/help`, `/cd <path>`, `/status`, `/clear`,
`/stop`, `/theme [name]`, `/quit`.

### 2. 7-Window Inbox Launcher

Runs the seven agents side by side, each listening for tasks in its own inbox.

```bat
launch_agents.bat            # launch all 7 agent windows
launch_agents.bat --smoke    # seed SMOKE tasks and run once
launch_agents.bat --dry      # print the launch commands only
```

Drop a single-line task into `_inbox/<agent>.task` (e.g. `_inbox/alex.task`).
The agent's window polls the inbox, runs the task, appends output to
`_logs/<agent>.log`, and moves the consumed task to `_inbox/done/`.

---

## Troubleshooting: "self signed certificate in certificate chain"

If agent runs fail with this opencode/Node error, a self-signed or
**intercepting certificate** (antivirus/EDR web filter, corporate proxy, or
network gateway) is in the chain of the LLM endpoint opencode talks to. Node
uses its own bundled CA store, so it rejects the injected root even though
browsers and `curl` succeed on the same machine.

Quick unblock (strictly opt-in; disables certificate verification **for the
opencode process only** — do not enable on untrusted networks):

```bat
set ZOVA_ALLOW_INSECURE_TLS=1
launch_agents.bat        :: or launch_terminal.bat
```

The toggle is honored by the 7-window inbox workers
(`scripts/run_agent_worker.ps1` / `.sh`) and by the ZOVA terminal's dispatch
engine (`scripts/core/run_hub.py`), which set
`NODE_TLS_REJECT_UNAUTHORIZED=0` for every `opencode run` they spawn. It is
**off by default** — leave it unset or `0` for normal TLS verification.

Preferred fix (keeps verification on): export the intercepting root CA from
the Windows certificate store (`certmgr.msc` → Trusted Root / your AV's cert →
Base-64 PEM) and point Node at it:

```bat
set NODE_EXTRA_CA_CERTS=C:\path\to\intercept-root.pem
```

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
├── AGENTS.md              # Agent roster, workflow, fallback policy, conventions
├── opencode.json          # Agent definitions, models, providers
├── launch_agents.bat      # 7-window inbox launcher
├── launch_terminal.bat    # ZOVA retro terminal launcher
├── scripts/
│   ├── terminal_app.py    # ZOVA retro terminal entry point (thin shim → core/ + ui/)
│   ├── core/              # Decoupled engine: agents, run hub, state
│   │   ├── agents/        # Per-agent definitions — one AgentSpec module per agent
│   │   │   ├── base.py        # AgentSpec dataclass (plain: identity + model)
│   │   │   ├── registry.py    # Roster + tab order derived from the specs
│   │   │   ├── matthew.py … chloe.py  # M1–M7 plain agents
│   │   │   ├── master.py      # Master coordinator spec
│   │   │   └── __main__.py    # CLI: resolve per-agent models for the launcher workers
│   │   ├── run_hub.py     # Thread-safe multi-agent execution engine (plain dispatch)
│   │   ├── state_tracker.py   # Session state (state.md)
│   │   └── command_parser.py  # Slash-command parsing + help text
│   ├── ui/                # Decoupled terminal UI (palette, rendering, theme)
│   ├── run_agent_worker.ps1  # Inbox-polling worker (Windows, 7-window launcher)
│   ├── run_agent_worker.sh   # Inbox-polling worker (Git Bash)
├── knowledge/             # Project memory (ADRs, lessons, metrics)
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

## Memory

Architecture decisions and lessons learned are appended to `knowledge/adr/` and
`knowledge/lessons/`. After a milestone, run the retro to summarize the session,
prune stale memory, and update these conventions.

See [`AGENTS.md`](AGENTS.md) for the complete control-plane documentation.

# MultiAgentCoding — Control Plane

A multi-agent coding system. This repository is the **control plane** that
defines the agents, configuration, and memory used to drive software projects.
It ships an Obsidian-inspired **Agent Dashboard** (primary interface), a
retro-CRT **ZOVA terminal** (fallback), and a 7-window inbox launcher.

> **Agent contract:** the seven roster agents are deliberately plain —
> **identity only** (tag/name/key), with model, role, and provider as *runtime*
> concerns — and dispatch is plain (`opencode run --agent <a> -m <model>
> "<prompt>"`). On top of that contract the repo ships an **Obsidian vault
> stack** (orchestrator, vault-bridge, context-resolver, knowledge-sync, health
> checks), the Agent Dashboard, Settings / BYOK provider connections, and a
> reusable **Role** system + **Project Profile** analyzer. See
> [`AGENTS.md`](AGENTS.md) for the full control-plane documentation.

---

## Overview

The control plane defines seven agents — Matthew, Alex, Sarah, David, Elena,
Max, and Chloe — configured in [`opencode.json`](opencode.json). Each agent is
an **identity** (tag/name/key) with a runtime model assignment and an explicit
fallback chain; the model is not part of the identity and can be changed at
runtime via the Settings / BYOK layer without editing any agent module.

| Agent | Default model |
|---|---|
| `matthew` | opencode/deepseek-v4-flash-free |
| `alex` | opencode/deepseek-v4-flash-free |
| `sarah` | opencode/deepseek-v4-flash-free |
| `david` | opencode/big-pickle |
| `elena` | opencode/ling-3.0-tiny-free |
| `max` | opencode/deepseek-v4-flash-free |
| `chloe` | opencode/ling-3.0-tiny-free |

> Defaults above; the live model is resolved from `opencode.json` at dispatch.

All default models are **free** (no paid credits required). Roles are defined
in [`roles.json`](roles.json) (many-to-many, model-independent); a repository
is analyzed into a `ProjectProfile` via `scripts/core/project_profile.py`. See
[`AGENTS.md`](AGENTS.md) for workflow and fallback-policy details.

---

## Prerequisites

- **Python 3.10+** (the code uses PEP 604 `X | Y` union type hints).
- **OpenCode CLI** — the control plane dispatches agents via
  `opencode run --agent <a> -m <model> "<prompt>"`.

Install the Python dependencies (the dashboard and retro terminal each need
them; the vault/orchestrator code is standard-library only):

```bash
python -m pip install -r requirements.txt          # runtime
python -m pip install -r requirements-dev.txt      # runtime + test (httpx)
```

Run the test suite:

```bash
python -m unittest discover -s test/tests
```

Two JavaScript tests (graph math + agent-session rendering) run separately
with Node and are **not** part of the Python suite:

```bash
node test/tests/graph_math.test.js
node test/tests/app_sessions.test.js
```

---

## Quick Start

### 1. Agent Dashboard (primary, Obsidian-inspired)

A local web dashboard that replaces the retro terminal as the default view.
It reuses the existing backend unchanged — the in-process `RunHub` for agent
dispatch, `VaultBridge`/`ContextResolver` for vault reads and safe writes, and
the real Orchestrator CLI for task execution — and adds a read-only graph view
of the managed vault plus an Obsidian-style panel layout.

```bash
launch_dashboard.bat                 # start server + open browser
python -m scripts.web_ui.server --no-browser   # start only (http://127.0.0.1:8790)
python -m scripts.web_ui.server --smoke        # headless build check
```

**Settings tab** — the Dashboard's Settings UI (Phase 25) manages **AI
connections** in two modes:

- **Simple** — known providers (Gemini, OpenAI, Anthropic): pick the provider
  and enter an API key; the endpoint/auth shape is auto-determined.
- **Advanced** — custom / OpenCode-style providers: name, Base URL, API key,
  auth method, and default models.

Keys are stored **only** in OpenCode's auth store
(`~/.local/share/opencode/auth.json`) via the `opencode auth login` CLI; the
frontend only ever sees `configured: true|false` — no endpoint returns a key.
The tab also edits per-agent models, modes, and fallback chains (with a
spec ↔ `opencode.json` drift check).

**Layout** — main area shows up to **6 agent panels** (name, model, status,
current task, live conversation, Stop), arranged in a 1/2/3/4/6 grid via the
toolbar selector. A **visibility menu** picks which ≤6 of the 7 agents appear.
The **left sidebar** holds a *small graph panel* — a force-laid-out view of the
vault's wiki-link graph, colored by folder — with a *related files / nodes*
list (links + backlinks) around it. Click a node to see related nodes, then
**Send context → active agent** to dispatch the node's resolved context to the
selected agent panel. The **bottom bar** has four tabs: **Status** (live table
of all agents), **Tasks** (inspect vault task nodes; assign an agent, set
status, or run the real orchestrator dispatch), **Execution** (live output of
task runs), and **Logs** (agents' / orchestrator log tails). Panels, sidebar,
and bottom bar are resizable via drag handles; layout and selection persist.

> The dashboard and the ZOVA terminal each own their own `RunHub`, so run one
> interface at a time — a prompt typed in one is not visible to the other.

### 2. ZOVA Retro Terminal (fallback)

Kept as the secondary interface. The interactive full-screen terminal UI:
retro-CRT styling with a bold pixel-art **ZOVA** banner, a live directory
status indicator, a **tab bar** (MASTER + one tab per agent), a model status
bar, a per-tab scrollable console, and a rounded prompt box at the bottom for
typing coding tasks or slash commands.

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

### 3. 7-Window Inbox Launcher

Runs the seven agents side by side, each listening for tasks in its own inbox.

```bat
launch_agents.bat            # launch all 7 agent windows
launch_agents.bat --smoke    # seed SMOKE tasks and run once
launch_agents.bat --dry      # print the launch commands only
```

Drop a single-line task into `_inbox/<agent>.task` (e.g. `_inbox/alex.task`).
The agent's window polls the inbox, runs the task, appends output to
`_logs/<agent>.log`, and moves the consumed task to `_inbox/done/`.

### 4. Obsidian Vault + Orchestrator

`obsidian_vault/` is a live, schema-validated Markdown vault (36 nodes). The
Orchestrator drives the same plain dispatch through **task nodes**: it reads a
`ready` task from `obsidian_vault/03-Tasks/`, resolves its assigned agent and
linked context, builds a bounded prompt, and dispatches through the same
`opencode run` command — always a dry run unless `--yes` is given.

```bash
python -m scripts.core.orchestrator list                          # task nodes
python -m scripts.core.orchestrator set-status Task_Demo ready     # transition
python -m scripts.core.orchestrator dispatch Task_Demo --yes       # authorized run
python scripts/vault_validate.py                                   # vault schema check
python scripts/generate_dashboard.py --check                       # dashboard freshness
python -m scripts.core.health_check                                # 11 read-only checks
```

---

## Plugins & Providers

Plugins are loaded from npm via the `plugin` array in
[`.opencode/opencode.json`](.opencode/opencode.json) (OpenCode resolves and
caches them automatically):

- **`@razroo/opencode-model-fallback`** — automatic model failover. Every agent
  carries a de-duplicated `fallback_models` chain in `opencode.json` (an
  agent's own primary model is never in its own chain); plugin behaviour is
  tuned in [`.opencode/opencode-model-fallback.jsonc`](.opencode/opencode-model-fallback.jsonc)
  (`cooldown_seconds: 0` = zero-wait failover, `max_fallback_attempts: 4`).
- **`opencode-hive`** — Agent Hive workflow layer (plan → approve → execute in
  git worktrees). Project config lives in `.hive/agent-hive.json` (gitignored
  runtime state).

Providers are defined in `opencode.json`: `ollama` (local
`qwen2.5-coder:7b`), `mulerouter` (aggregator — unused by default, kept for the
Settings UI), and the built-in `opencode` provider models
(`opencode/big-pickle`, `opencode/deepseek-v4-flash-free`,
`opencode/ling-3.0-tiny-free` — all free-tier models). Keys live only in
`~/.local/share/opencode/auth.json`, never in the repo.

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
├── opencode.json          # Runtime config: agents, models, providers, fallback
├── roles.json             # Reusable roles + many-to-many agent assignments
├── launch_agents.bat      # 7-window inbox launcher
├── launch_terminal.bat    # ZOVA retro terminal launcher (fallback)
├── launch_dashboard.bat   # Agent Dashboard launcher (primary)
├── scripts/
│   ├── terminal_app.py    # ZOVA retro terminal entry point (thin shim → core/ + ui/)
│   ├── vault_validate.py  # Vault node schema validator (36 nodes OK)
│   ├── generate_dashboard.py  # Regenerates the Dashboard's GENERATED block
│   ├── web_ui/            # Agent Dashboard — primary Obsidian-inspired UI
│   │   ├── server.py      # FastAPI app factory + uvicorn entry (--smoke)
│   │   ├── routes.py      # REST/SSE endpoints (thin layer over core)
│   │   ├── state.py       # WebState: drains HUB events into per-agent sessions
│   │   ├── graph.py       # VaultGraph: read-only node/edge model of the vault
│   │   ├── settings.py    # Settings facade: connections, keys (auth store only), models
│   │   └── static/        # index.html · app.css · app.js (vanilla, no build)
│   ├── core/              # Decoupled engine: agents, run hub, state, vault stack
│   │   ├── agents/        # Per-agent identity — one AgentSpec module per agent
│   │   │   ├── base.py        # AgentSpec dataclass (identity only: tag/name/key)
│   │   │   ├── registry.py    # Roster + tab order derived from the specs
│   │   │   ├── matthew.py … chloe.py  # M1–M7 agents (identity only)
│   │   │   ├── master.py      # Master coordinator spec
│   │   │   └── __main__.py    # CLI: resolve per-agent runtime models from opencode.json
│   │   ├── roles.py       # Reusable roles + many-to-many assignment (roles.json)
│   │   ├── project_profile.py  # Repository analysis → ProjectProfile + suggested roles
│   │   ├── run_hub.py     # Thread-safe multi-agent execution engine (plain dispatch)
│   │   ├── orchestrator.py    # Vault task dispatch (ready-gate, --yes, locks)
│   │   ├── vault_bridge.py    # Scoped vault I/O (atomic writes, backups, frontmatter)
│   │   ├── context_resolver.py  # Bounded linked-context resolution from a node
│   │   ├── change_detector.py   # Snapshot diff → vault-node impact mapping
│   │   ├── knowledge_sync.py    # Docs ↔ code drift sync (dry-run by default)
│   │   ├── health_check.py      # 11 read-only vault/workspace checks
│   │   ├── state_tracker.py     # Session state (state.md)
│   │   ├── command_parser.py    # Slash-command parsing + help text
│   │   └── opencode_cfg.py      # Single source of truth for runtime models (atomic, rollback)
│   ├── ui/                # Decoupled terminal UI (palette, rendering, theme)
│   ├── run_agent_worker.ps1  # Inbox-polling worker (Windows, 7-window launcher)
│   ├── run_agent_worker.sh   # Inbox-polling worker (Git Bash)
├── knowledge/             # Project memory (ADRs, lessons, metrics)
├── obsidian_vault/        # Live vault: 00-System … 06-Testing + Dashboard.md
├── .opencode/             # opencode plugins/config (model fallback, opencode-hive)
└── .vscode/               # VS Code tasks (Launch All Agents / Dashboard / ZOVA)
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

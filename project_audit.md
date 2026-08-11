# project_audit.md — Project & Environment Audit

> **Step [01/20] deliverable.** Read-only audit: no project files were created,
> modified, renamed, moved, or deleted. No agents created. No architecture
> changed. No Obsidian install attempted, no vault created.
> Audit run: 2026-08-11 UTC.

---

## 1. Project Root

```
C:\Users\meins\Documents\coding\projects\multi_agent_coding
```

- Git repository, branch **`pre-reset`**; HEAD `fe65493 refactor(core): perform complete zero-baseline system reset`.
- The working tree has **uncommitted changes** (the zero-baseline reset is in
  flight: many legacy modules deleted, remaining files modified). See §9.
- Per `AGENTS.md`, this is the **control plane** for a 7-agent coding system at
  **baseline-zero**: plain agents (identity + model only), plain dispatch
  (`opencode run --agent <a> -m <model> "<prompt>"`), all external integrations
  (Obsidian archivist, analyzer, swarm, self-evolve, web dashboard) removed.

## 2. Technology Stack

| Layer | Technology | Evidence |
|---|---|---|
| Runtime / core engine | **Python 3.11.15** | `python --version`; `scripts/core/*.py` |
| Terminal UI | **prompt_toolkit** | `scripts/ui/terminal_app.py` imports |
| AI agent runtime | **opencode CLI v1.18.16** | `opencode --version`; `RunHub._build_run_command` |
| Local model provider | **Ollama** (`qwen2.5-coder:7b`) | `opencode.json` provider block |
| Fallback plugin | **@razroo/opencode-model-fallback** + **opencode-hive** | `.opencode/opencode.json`, `.opencode/` node_modules |
| Node toolchain | **Node v26.5.0, npm 11.17.0** | `node --version`, `npm --version` |
| Version control | **Git 2.55.0.windows.2** | `git --version` |
| Launchers | **Windows Batch** + **PowerShell 5.1** + **Git Bash** | `launch_agents.bat`, `scripts/run_agent_worker.ps1` / `.sh` |
| Tests | **unittest** (stdlib) | `test/tests/` — 201 tests, OK (1 skipped) |
| Docs / metadata | Markdown, JSON | `README.md`, `AGENTS.md`, `state.md`, `TASKS.json`, `obsidian_vault/` |

## 3. Directory Tree

```
multi_agent_coding/
├── AGENTS.md                    # Agent roster, workflow, conventions, fallback policy
├── README.md                    # Project documentation
├── PLAN.md                      # ARCHIVED (superseded by baseline-zero reset)
├── TASKS.json                   # Stale swarm-era task list (T1–T11; T9–T11 pending)
├── state.md                     # Runtime session state (phase/last-run/completed/restart log)
├── opencode.json                # OpenCode runtime config: agents, models, providers, fallback
├── opencode.json.bak            # Pre-reset backup (gitignored; contains a legacy 9router key block)
├── project_audit.md             # This report (untracked, step [01/20] deliverable)
├── launch_agents.bat            # 7-window inbox launcher
├── launch_terminal.bat          # ZOVA retro terminal launcher
│
├── .gitignore
├── .opencode/                   # OpenCode plugins & config
│   ├── opencode.json            #   plugin list: model-fallback, opencode-hive
│   ├── opencode-model-fallback.jsonc
│   ├── package.json / package-lock.json
│   ├── skills/
│   │   ├── agent-team-sizing/SKILL.md
│   │   └── prompt-engineering/SKILL.md
│   └── node_modules/
├── .vscode/tasks.json           # "Launch All Agents" (M1–M7) + ZOVA terminal tasks
├── .hive/                       # opencode-hive orchestration state (gitignored)
│
├── scripts/
│   ├── terminal_app.py          # ZOVA terminal entry point (thin shim → core/ + ui/)
│   ├── core/
│   │   ├── __init__.py          #   re-exports agents/progress/run_hub/state/commands
│   │   ├── agents/              #   one AgentSpec module per agent + registry
│   │   │   ├── base.py          #     AgentSpec dataclass (tag/name/agent/model)
│   │   │   ├── constants.py     #     PROJECT_ROOT + status values
│   │   │   ├── registry.py      #     AGENTS / TABS derived from specs
│   │   │   ├── matthew.py … chloe.py, master.py, __main__.py (CLI: list/roster/model/verify)
│   │   ├── run_hub.py           #   thread-safe multi-agent execution engine (HUB)
│   │   ├── state_tracker.py     #   state.md read/write (STATE)
│   │   ├── command_parser.py    #   slash-command parsing + help text
│   │   └── progress.py          #   token estimation + weighted progress aggregation
│   ├── ui/
│   │   ├── terminal_app.py      #   full-screen prompt_toolkit app (RetroTerminalApp)
│   │   ├── rendering.py         #   console fragments, panels, loading bar
│   │   ├── palette.py           #   colors, banner, status symbols, layout constants
│   │   └── theme.py             #   Theme dataclass + classic/opencode themes
│   ├── run_agent_worker.ps1     # Inbox-polling worker (Windows, 7-window launcher)
│   └── run_agent_worker.sh      # Inbox-polling worker (Git Bash)
│
├── docs/architecture/Architecture.md   # Baseline-zero system map (Mermaid)
├── knowledge/                           # Swarm memory (referenced by opencode.json)
│   ├── README.md
│   ├── lessons/2026-08-07-groq-tpm-vs-opencode-request.md
│   ├── fine_tune_dataset.jsonl (0 B) + metrics.jsonl (0 B)
│   └── (adr/ documented but absent)
│
├── obsidian_vault/              # Static Markdown vault (NOT connected to Obsidian app)
│   ├── Dashboard.md, Roadmap.md
│   ├── prompts/                 # _TEMPLATE.md + prompt-001 … prompt-1072 (near-identical logs)
│   └── agents_logs/             # _TEMPLATE.md + 23 per-agent log .md files (M1–M7, legacy roles)
│
├── test/                        # Sample target project (expense tracker, Persian docs)
│   ├── app.py, expense_manager.py, expense_tracker.py
│   ├── PLAN.md, TASKS.json, README.md, __init__.py
│   └── tests/                   # test_agents, test_agent_specs, test_expense_manager, test_terminal_app
│
├── ui new/                      # Stray untracked dir containing only .hive/ (junk)
├── _inbox/                      # Runtime inbox (gitignored) — <agent>.task files + done/
└── _logs/                       # Runtime logs (gitignored) — per-agent .log + legacy swarm logs
```

## 4. Existing Agents

Seven plain agents (identity + model only), defined one `AgentSpec` module per
agent in `scripts/core/agents/`, roster derived in `registry.py`, mirrored in
`opencode.json` (drift-checked by `python -m scripts.core.agents verify`):

| Tab | Agent key | Name | Model |
|---|---|---|---|
| M1 | `matthew` | Matthew | `opencode/deepseek-v4-flash-free` |
| M2 | `alex` | Alex | `opencode/deepseek-v4-flash-free` |
| M3 | `sarah` | Sarah | `opencode/deepseek-v4-flash-free` |
| M4 | `david` | David | `opencode/big-pickle` |
| M5 | `elena` | Elena | `opencode/ling-3.0-tiny-free` |
| M6 | `max` | Max | `opencode/deepseek-v4-flash-free` |
| M7 | `chloe` | Chloe | `opencode/ling-3.0-tiny-free` |

Plus the **MASTER** coordinator tab (`master.py`, `agent=None`, dispatches to all
enabled agents). All agents are `mode: all`, `description: "M# — plain agent."`,
and share the fallback chain `[opencode/big-pickle, opencode/deepseek-v4-flash-free,
ollama/qwen2.5-coder:7b]`. The legacy role-based roster (system-architect,
analyst, planner, backend-dev, frontend-dev, tester, reviewer) exists only in
`opencode.json.bak`, `_logs/`, `obsidian_vault/agents_logs/`, and `TASKS.json`
— all stale artifacts of the pre-reset era.

## 5. Existing Scripts

| Script | Purpose |
|---|---|
| `launch_agents.bat` | 7-window inbox launcher; builds roster from `python -m scripts.core.agents roster`; `--smoke` / `--dry` / `--help` |
| `launch_terminal.bat` | Launches the ZOVA retro terminal (`python scripts/terminal_app.py [--workspace DIR] [--smoke]`) |
| `scripts/terminal_app.py` | Thin shim entry point re-exporting `scripts/core/*` and `scripts/ui/*` |
| `scripts/core/agents/__main__.py` | CLI: `list`, `roster`, `model <tag>`, `verify` (specs ↔ opencode.json drift check) |
| `scripts/core/run_hub.py` | Thread-safe execution engine: one worker thread per agent streaming `opencode run --agent <a> --auto -m <m> "<prompt>"`; statuses/progress/token telemetry; terminate/abort |
| `scripts/core/state_tracker.py` | Atomic read/write of `state.md` (phase, last run, completed, restart log) |
| `scripts/core/command_parser.py` | Slash-command splitter + `/help` text |
| `scripts/core/progress.py` | Token-percent estimation + weighted master progress aggregation |
| `scripts/ui/terminal_app.py` | `RetroTerminalApp` — full-screen prompt_toolkit UI (tabs F1–F8, console, loading bar, rounded prompt box, themes) |
| `scripts/ui/rendering.py` | Fragment renderers (dashboard, panels, loading bar, model bar, diff colors) |
| `scripts/ui/palette.py` | Palette constants, ASCII banner, status symbols |
| `scripts/ui/theme.py` | Theme dataclass + `classic` / `opencode` themes |
| `scripts/run_agent_worker.ps1` | Inbox-polling worker (Windows): resolves model via specs, runs task, logs to `_logs/<agent>.log`, moves task to `_inbox/done/`, 4×2 grid placement, optional TLS bypass |
| `scripts/run_agent_worker.sh` | Same worker for Git Bash (`--dry` support) |

## 6. Existing Configuration Files

| File | Purpose |
|---|---|
| `opencode.json` | OpenCode runtime: `default_agent: matthew`, model/small_model, `instructions: [AGENTS.md]`, `references.knowledge → ./knowledge`, providers (ollama, mulerouter), 7 agents + compaction |
| `opencode.json.bak` | Pre-reset backup (gitignored) — legacy role agents; **contains a hardcoded 9router API key block** (`sk-…`) — security cleanup item, tracked only as `opencode.json.bak` which is gitignored |
| `.opencode/opencode.json` | Plugin list: `@razroo/opencode-model-fallback`, `opencode-hive` |
| `.opencode/opencode-model-fallback.jsonc` | Fallback policy: retry on 429/5xx, retryable error patterns, `max_fallback_attempts: 4`, `cooldown_seconds: 0`, global chain |
| `.opencode/package.json` / `package-lock.json` | Node deps: `@opencode-ai/plugin` 1.18.14 |
| `.opencode/skills/` | `agent-team-sizing/SKILL.md`, `prompt-engineering/SKILL.md` |
| `.vscode/tasks.json` | VS Code tasks: M1–M7 workers, `Launch All Agents` (parallel), `Launch ZOVA Retro Terminal` |
| `.gitignore` | Secrets (`*.pem`, `auth.json`, `opencode.json.bak`), runtime (`knowledge/index.jsonl`, `_logs/`, `_inbox/`), `node_modules/`, `__pycache__/`, `.hive/` |
| `AGENTS.md` | Control-plane conventions (also loaded by opencode as instructions) |
| `TASKS.json` (root) | Stale swarm-era task tracking — T1–T8 done, T9 (secret removal) / T10 (E2E) / T11 (commit) **pending** |
| `test/TASKS.json` | Sample-project task tracking |

## 7. Existing Documentation

- `README.md` — overview, ZOVA terminal + 7-window launcher docs, troubleshooting, project layout.
- `AGENTS.md` — roster, workflow, conventions, fallback policy, execution environment.
- `PLAN.md` — **ARCHIVED** (2026-08-11): swarm role-swapping / self-evolve / archivist plan kept as historical record.
- `docs/architecture/Architecture.md` — baseline-zero system map (Mermaid flowchart).
- `state.md` — runtime state checkpoint (phase `running`, last-run, completed log, ~200+ restart-log entries).
- `knowledge/README.md` + `knowledge/lessons/` — memory conventions and one lesson.
- `obsidian_vault/Dashboard.md`, `Roadmap.md`, `prompts/` (1073 files), `agents_logs/` (23 files) — static Markdown vault.
- `test/README.md`, `test/PLAN.md` — sample project docs (Persian).

## 8. Current Integrations Between Components

```
┌──────────────────────────── ZOVA Terminal (scripts/terminal_app.py shim)
│   scripts/ui/terminal_app.py (RetroTerminalApp)
│     ├─ reads roster from  scripts/core/agents/registry.py  (AGENTS/TABS)
│     ├─ renders via        scripts/ui/{palette,rendering,theme}.py
│     └─ drives dispatch    scripts/core/run_hub.py (HUB)
│                              ├─ builds `opencode run --agent <a> --auto -m <m> "<prompt>"`
│                              │    → subprocess (one thread per agent)
│                              ├─ records session state → scripts/core/state_tracker.py → state.md
│                              └─ progress telemetry ← scripts/core/progress.py
└─────────────┬──────────────────────────────
  7-Window Launcher (launch_agents.bat → run_agent_worker.ps1/.sh)
      ├─ resolves models via `python -m scripts.core.agents model <a>` (specs = source of truth)
      ├─ polls _inbox/<agent>.task → runs opencode → appends _logs/<agent>.log → moves to _inbox/done/
      └─ honors ZOVA_ALLOW_INSECURE_TLS=1 → NODE_TLS_REJECT_UNAUTHORIZED=0

opencode.json / .opencode/*  ← agent models, providers (ollama/mulerouter),
   fallback chain (@razroo plugin), knowledge/ reference, AGENTS.md instructions,
   opencode-hive (.hive/ orchestration state)
```

Key data flows:
1. **Specs → everywhere**: `scripts/core/agents/*.py` is the single source of
   truth; `registry.py` derives roster; `__main__.py` CLI feeds the launcher
   (`roster`, `model`) and drift-checks against `opencode.json` (`verify`).
2. **Terminal → RunHub → opencode**: typed tasks dispatch to the active tab's
   agent (or all on MASTER) via thread-per-agent subprocess; output streams
   into per-tag buffers rendered as categorized panels.
3. **State persistence**: `StateTracker` writes `state.md` atomically on each
   run start/finish/abort.
4. **Fallback failover**: `@razroo/opencode-model-fallback` auto-switches
   within the configured chain on rate limits / server errors / context
   exhaustion (zero cooldown).
5. **Knowledge reference**: `./knowledge` is wired as an opencode `references`
   path (consulted before planning/reviewing).

## 9. Obsidian Installation Status

**Obsidian is NOT installed.** All detection methods were negative:

- Binary: no `Obsidian.exe` in `%LOCALAPPDATA%\Obsidian`, `%PROGRAMFILES%`, or `%PROGRAMFILES(x86)%`; not on `PATH` (`where obsidian` / `command -v obsidian` empty).
- Vault registry: `%APPDATA%\obsidian\obsidian.json` does **not** exist.
- Registry key `HKCU\Software\Classes\obsidian`: not found.
- Start Menu (user + all-users): no Obsidian entry.
- `winget list --id Obsidian.Obsidian`: "No installed package found".

**Per step requirements:** no automatic install was attempted — Obsidian must
be installed manually (https://obsidian.md). No vault path can be auto-detected
or asked for yet; the repo's embedded `obsidian_vault/` folder is currently a
**static Markdown tree only** (not a live Obsidian vault, no `.obsidian/` config
dir) — it is a candidate to be opened as a vault once Obsidian is installed.

## 10. Recommended Next Step

1. **Install Obsidian manually** (https://obsidian.md — Windows installer).
2. After installation, either open the repo's existing `obsidian_vault/`
   folder as the vault, or provide the path of an existing vault to connect.
3. Then define the vault↔control-plane wiring (step [02/20]) deliberately —
   without re-adding the removed archivist machinery — e.g. vault as
   documentation store, agent log mirror, or knowledge graph.
4. Cleanup candidates for later steps (flagged, not acted on):
   - `opencode.json.bak` contains a legacy hardcoded `9router` API key (file is
     gitignored, but should be deleted or scrubbed).
   - Root `TASKS.json` still tracks removed swarm tasks; `_logs/` and
     `obsidian_vault/agents_logs/` hold pre-reset role-era artifacts.
   - Stray untracked `ui new/` directory (contains only `.hive/`).

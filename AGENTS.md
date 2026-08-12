# AGENTS.md — MultiAgentCoding Control Plane

This repository is the **control plane** for a multi-agent coding system. It
holds the MultiAgentCoding configuration, agent definitions, and memory used to
drive software projects.

**Baseline-zero status:** the system is a plain, unopinionated slate. Seven
agents are defined by identity and model only — no roles, operational modes,
specialized prompts, or behavioral wrappers. Dispatch is plain
(`opencode run --agent <a> -m <model> "<prompt>"`). All external integrations
(Obsidian archivist, analyzer, swarm, self-evolve) have been removed. The
intent is to rebuild capabilities deliberately, step by step.

## Agents

| Agent | Model |
|---|---|
| `matthew` | opencode/deepseek-v4-flash-free |
| `alex` | opencode/deepseek-v4-flash-free |
| `sarah` | opencode/deepseek-v4-flash-free |
| `david` | opencode/big-pickle |
| `elena` | opencode/ling-3.0-tiny-free |
| `max` | opencode/deepseek-v4-flash-free |
| `chloe` | opencode/ling-3.0-tiny-free |

Every agent carries an explicit `fallback_models` chain (see
[Fallback Policy](#fallback-policy)). All models are free (no paid credits).

## Workflow

There is no fixed pipeline: any task typed into the terminal is dispatched to
the active tab's agent (or, on MASTER, to all agents) with that agent's
configured model. The operator sequences handoffs by dispatching the next task
after a previous run completes.

## Conventions

- Never commit secrets. Keys live only in `~/.local/share/opencode/auth.json`.
- Never commit `knowledge/index.jsonl` or anything under `_logs/`.
- Consult `knowledge/` (via the `knowledge` reference) before planning or
  reviewing.
- Keep `PLAN.md` and `TASKS.json` at the project root of the target project.
- Commits are small and single-purpose; branch pattern `feature/{agent}-{task}`.
- Agent definitions live in `scripts/core/agents/` — one `AgentSpec` module per
  agent (`matthew.py` … `chloe.py`) plus `master.py`. The `registry` derives the
  roster and tab order from those specs, so edit an agent there (not in
  `terminal_app.py` or `opencode.json`) to keep each agent independently
  configurable, testable, and modifiable. `python -m scripts.core.agents verify`
  checks the specs stay in sync with `opencode.json` (exit 1 on drift).

## Fallback Policy

Every agent carries an explicit ordered `fallback_models` chain in `opencode.json`.
The `@razroo/opencode-model-fallback` plugin (loaded via `.opencode/opencode.json`)
automatically switches to the next model in the chain when a request fails; opencode
itself only retries the same model, so this plugin is what makes failover real.

- **Chain (all 7 agents, in priority order):**
  1. `opencode/big-pickle` — Priority 1 fallback.
  2. `opencode/deepseek-v4-flash-free` — Priority 1 fallback (fast, reliable).
  3. `ollama/qwen2.5-coder:7b` — Priority 2 fallback (local, zero external cost).
- **Triggers** — the plugin falls back on: Rate Limit (HTTP 429), server errors
  (500/502/503/504/507), token limits, context exhaustion ("context length",
  "input is too long", "maximum context"), quota/usage-limit/credit-balance, and
  model-not-found.
- **Zero-wait failover** — `cooldown_seconds: 0` in
  `.opencode/opencode-model-fallback.jsonc` so a failed model is retried
  immediately on the next turn; no backoff delays, the workflow never halts.
- **Launcher note** — the worker passes `-m <primary>` which pins the session to
  the agent's primary model at launch; within that session, the plugin's fallback
  chain still applies on error. The chains also apply to any interactive or
  subagent use of these agents.

## Execution Environment (Windows)

This repo ships a human-facing UI plus a 7-window launcher.

- **Primary interface — Agent Dashboard** (`scripts/web_ui/`): an
  Obsidian-inspired local web dashboard (FastAPI + browser). `launch_dashboard.bat`
  starts it at http://127.0.0.1:8790, or use the `Launch Agent Dashboard`
  VS Code task. It reuses the backend unchanged: in-process RunHub for agent
  dispatch, VaultBridge/ContextResolver for vault I/O and node context, and the
  real Orchestrator CLI (`python -m scripts.core.orchestrator dispatch <Task>
  --yes`) for task runs. It shows up to 6 agent panels (1/2/3/4/6 layouts), a
  read-only vault graph + related-files sidebar, and Status/Tasks/Execution/
  Logs tabs. New code lives under `scripts/web_ui/` only; core is never modified
  by the UI (assigning a task writes `assigned_agent` via VaultBridge; status
  transitions and dispatch go through the orchestrator pipeline).
- **Steps:** The web dashboard, the ZOVA terminal, and the inbox workers each
  drive their own agent runs; run one interface at a time.
- **7-window launcher** — `launch_agents.bat` opens seven terminal windows,
  titled `M1 - Matthew` … `M7 - Chloe`, positioned in a 4×2 grid.

### Task inbox flow (7-window launcher)

Drop a single-line task into `_inbox/<agent>.task`
  (e.g. `_inbox/alex.task`). The agent's window polls the inbox, runs
  `opencode run --agent <name> -m <model> "<task>"`, appends the full output to
  `_logs/<agent>.log`, then moves the consumed task to `_inbox/done/`. Poll
  interval is 3s.
- **Window map** — `M1` matthew, `M2` alex, `M3` sarah,
  `M4` david, `M5` elena, `M6` max, `M7` chloe.
- **Event-driven handoff** — each agent processes its inbox independently. To
  hand work to the next agent, drop the next task into that agent's inbox after
  the previous one logs completion. There is no shared queue; the operator (or
  a driving agent) sequences the drops.
- **TLS note** — if agent runs fail with `self signed certificate in
  certificate chain` (opencode/Node rejecting a self-signed or intercepting
  cert), set `ZOVA_ALLOW_INSECURE_TLS=1` before launching to run opencode
  with `NODE_TLS_REJECT_UNAUTHORIZED=0` (opt-in; off by default). See
  `README.md` → Troubleshooting for the preferred `NODE_EXTRA_CA_CERTS` fix.
- **Models** — the worker resolves each agent's configured model from its
  `AgentSpec` (`scripts/core/agents/`, via `python -m scripts.core.agents
  model <agent>`; see the [Conventions](#conventions) note on agent
  definitions) and passes it explicitly (`-m`) so the agent's own model is
  used. `opencode.json` remains the OpenCode runtime config but is no longer
  parsed by the launcher. `-m` pins the session to the primary model at
  launch, but the model-fallback plugin still applies its chain on any
  failure within that session (see [Fallback Policy](#fallback-policy)).
  The MuleRouter provider block remains defined in `opencode.json` but is no
  longer used by default; its API key lives only in
  `~/.local/share/opencode/auth.json` (never committed).
- **Mode note** — all 7 agents are `mode: all`: they can be invoked standalone
  (`opencode run --agent X`) and still be used as subagents by other agents.

## Memory

Architecture decisions and lessons learned are appended to `knowledge/adr/` and
`knowledge/lessons/`. After a milestone, summarize the session, prune stale
memory, and update these conventions.

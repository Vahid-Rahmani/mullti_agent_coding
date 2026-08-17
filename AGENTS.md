# AGENTS.md — MultiAgentCoding Control Plane

This repository is the **control plane** for a multi-agent coding system. It
holds the MultiAgentCoding configuration, agent definitions, and memory used to
drive software projects.

**Agent contract:** the seven roster agents are deliberately plain —
**identity only** (tag/name/agent key). An `AgentSpec` never pins a model,
role, or provider; those are runtime concerns composed at dispatch time.
Dispatch is plain (`opencode run --agent <a> -m <model> "<prompt>"`). The
legacy swarm/self-evolve/archivist machinery stays removed.

**Decoupled concepts** — the architecture strictly separates these and never
permanently couples them:

1. **Agent** — independent execution identity (`AgentSpec`: tag/name/key only).
2. **Role** — reusable expertise/behavior (responsibilities, tools, permissions,
   rules, expected outputs), defined in `roles.json` and assigned many-to-many
   to agents via `scripts/core/roles.py`.
3. **Skill** — a reusable *operating procedure* (ordered steps + capabilities)
   that sits between a role and the prompt/workflow layer
   (`scripts/core/skills.py`). Model- and agent-independent, composable by id
   from workflow nodes, provenance-aware where adapted from external research.
4. **Model / provider** — a runtime selection owned by `opencode.json` and the
   Settings / BYOK layer (`scripts/core/opencode_cfg.resolve_model`).
5. **Evaluation** — a reusable output rubric (`scripts/core/evaluation.py`):
   criteria dimensions, weighted scoring, and a pass/review/fail decision.
6. **Project / repository context** — a `ProjectProfile` derived read-only by
   `scripts/core/project_profile.py` (technologies, manifests, instructions,
   suggested roles) and injected dynamically, never duplicated per agent.
7. **Agent Catalog / Preset** — the deterministic template layer
   (`scripts/core/agent_catalog.py`): hand-curated `AgentPreset`s grouped under
   high-level categories, plus a special **Empty Agent** (zero configuration).
   A preset pins one deliberate role + skills + prompt profile(s) and
   references an existing agent key; it is never synthesized from roles ×
   prompts, and the existing 7 agents are preserved as the runtime identities.

So **any agent can run on any user-selected model**, and **any role can be
assigned to one or many agents** (and an agent may hold many roles) without
editing an agent's source module. Categories and presets are **templates**,
never runtime identities: selecting a preset populates role/skills/prompt
profile deterministically, and the Empty Agent stays empty (raw request only).

**Runtime context** — the decoupled concepts are *composed* into one
**deterministic prompt** at dispatch time by `scripts/core/runtime_context.py`
(identity → roles → skills → prompt profile/instruction → project → workflow →
task → user request). Every execution path (terminal RunHub, task
Orchestrator, workflow planner) uses the same builder, so an agent's configured
roles/skills/prompt profiles actually reach its runtime prompt. Per-agent skill
and prompt-profile assignments persist in `agent_context.json`
(`$ZOVA_AGENT_CONTEXT` overrides) and are editable via the Settings API. The
order is fixed so task/user text can never overwrite system-level identity.

On top of that plain contract the repo ships an **Obsidian vault stack**
(`scripts/core/vault_bridge.py`, `orchestrator.py`, `context_resolver.py`,
`change_detector.py`, `knowledge_sync.py`, `health_check.py` +
`scripts/generate_dashboard.py`, `scripts/vault_validate.py`) that coordinates
the same plain dispatch through task nodes, plus the **Agent Dashboard**
(`scripts/web_ui/`) and the **Settings / BYOK connections** facade
(`scripts/web_ui/settings.py`). The runtime control plane (agents, models,
fallback) lives in `opencode.json`; the specs under `scripts/core/agents/`
carry identity only and mirror the roster.

## Agents

Seven roster agents — **identity only**: `matthew`, `alex`, `sarah`, `david`,
`elena`, `max`, `chloe` (tags `m1`…`m7`, keys lowercased names). Each carries a
`fallback_models` chain in `opencode.json` (see
[Fallback Policy](#fallback-policy)).

Models are **not part of an agent's identity**. The runtime model for each
agent is resolved from `opencode.json` at dispatch time
(`opencode_cfg.resolve_model(agent)`), which the Settings / BYOK layer can
change at runtime. All default models are free (no paid credits).

## Roles

Roles are reusable, model-independent definitions stored in **`roles.json`**
at the repo root (override with `$ZOVA_ROLES`). A role has `name`,
`description`, `responsibilities`, `tools`, `permissions`, `rules`, and
`expected_outputs`. The `assignments` map is many-to-many: one agent may hold
many roles, and many agents may share one role.

- Predefined roles ship in `roles.json` (e.g. `python-developer`,
  `fastapi-developer`, `software-architect`, `security-engineer`, `qa-engineer`,
  `code-reviewer`, `devops-engineer`, `ai-agent-engineer`).
- Custom roles are created/edited via `scripts/core/roles.py` (or the Dashboard
  Settings API) — **without** editing any agent module.
- Assignments are edited via `scripts.core/roles.assign_roles(agent, [ids])`
  (or the API); reassigning a role never changes an agent's model, and changing
  an agent's model never changes its role.
- Precedence for resolving effective agent context (highest first): explicit
  user instruction > user-selected role > repository instructions (AGENTS.md) >
  assigned role defaults > generic agent defaults.

## Project Profile

`scripts/core/project_profile.py` analyzes a repository read-only (README,
AGENTS.md, package manifests, source tree, CI/Docker config) into a
`ProjectProfile` (technologies, manifests, instructions, detected/suggested/
approved roles). Suggested roles are **never auto-applied** — the user approves
one by defining + assigning it in `roles.json`. The profile is injected into
dispatch context dynamically, not duplicated into each agent's config.

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
- Agent **identity** lives in `scripts/core/agents/` — one `AgentSpec` module per
  agent (`matthew.py` … `chloe.py`) plus `master.py`. The `registry` derives the
  roster and tab order from those specs. An `AgentSpec` carries tag/name/key
  **only** — never a model, role, or provider. To change an agent's *model*,
  edit `opencode.json` (or the Settings API); to change its *roles*, edit
  `roles.json`. `python -m scripts.core.agents verify` checks the roster's
  mode/fallback invariants against `opencode.json` (exit 1 on drift).

## Fallback Policy

Every agent carries an explicit ordered `fallback_models` chain in `opencode.json`.
The `@razroo/opencode-model-fallback` plugin (loaded via `.opencode/opencode.json`)
automatically switches to the next model in the chain when a request fails; opencode
itself only retries the same model, so this plugin is what makes failover real.

- **Fallback pool (in priority order):**
  1. `opencode/big-pickle` — Priority 1 fallback.
  2. `opencode/deepseek-v4-flash-free` — Priority 1 fallback (fast, reliable).
  3. `ollama/qwen2.5-coder:7b` — Priority 2 fallback (local, zero external cost).
- **Per-agent chains are de-duplicated** — an agent's own primary model never
  appears in its own `fallback_models` chain (retrying a just-failed model is
  a wasted attempt, and with `cooldown_seconds: 0` nothing stays in cooldown):
  - deepseek-primary agents (`matthew`, `alex`, `sarah`, `max`):
    `[opencode/big-pickle, ollama/qwen2.5-coder:7b]`
  - big-pickle-primary agent (`david`):
    `[opencode/deepseek-v4-flash-free, ollama/qwen2.5-coder:7b]`
  - ling-primary agents (`elena`, `chloe`):
    `[opencode/big-pickle, opencode/deepseek-v4-flash-free, ollama/qwen2.5-coder:7b]`
  The global chain in `.opencode/opencode-model-fallback.jsonc` applies to
  agents without their own chain (e.g. the `opencode-hive` agents).
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
- **Obsidian vault stack** — `obsidian_vault/` is a live, schema-validated
  vault (40 nodes, including 4 seeded task nodes in `03-Tasks/`). The
  Orchestrator (`python -m scripts.core.orchestrator`) dispatches `ready` task
  nodes through the same `opencode run` command the terminal uses, enforces
  status transitions + per-task locks, and requires an explicit `--yes` to
  execute. A completed/failed run writes the outcome **and** a structured
  `## Agent Report` back into the node (`GET /api/tasks/{name}` returns the
  persisted result). Task statuses use the Orchestrator vocabulary
  (`planned`/`ready`/`in_progress`/`blocked`/`completed`/`failed`), which the
  vault validator now enforces. `vault_validate.py`, `generate_dashboard.py
  --check`, and `health_check.py` keep the vault schema-valid and drift-free.
- **Settings / BYOK** — the Dashboard's Settings tab (Phase 25) manages
  provider connections (Simple: Gemini/OpenAI/Anthropic; Advanced: custom
  Base URL) and per-agent models/modes/fallback chains. API keys are stored
  **only** in `~/.local/share/opencode/auth.json`; the backend never returns a
  key to the frontend.
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
- **Models** — the worker resolves each agent's configured model from
  `opencode.json` (via `python -m scripts.core.agents model <agent>`) and
  passes it explicitly (`-m`); the agent's model is a runtime value, not a
  spec field. `-m` pins the session to that model at launch, but the
  model-fallback plugin still applies its chain on any failure within that
  session (see [Fallback Policy](#fallback-policy)).
  The MuleRouter provider block remains defined in `opencode.json` but is no
  longer used by default; its API key lives only in
  `~/.local/share/opencode/auth.json` (never committed).
- **Mode note** — all 7 agents are `mode: all`: they can be invoked standalone
  (`opencode run --agent X`) and still be used as subagents by other agents.
  Agents pinned to `mode: subagent` are refused by `opencode run --agent`
  (opencode falls back to the default agent with a warning), so every roster
  agent must stay `all` (or `primary`). `default_agent: matthew` is a primary-
  capable agent, which the schema requires.

## Memory

Architecture decisions and lessons learned are appended to `knowledge/adr/` and
`knowledge/lessons/`. External research sources are registered in
`knowledge/sources/` (one record per upstream repository, with license and
provenance). After a milestone, summarize the session, prune stale memory, and
update these conventions.

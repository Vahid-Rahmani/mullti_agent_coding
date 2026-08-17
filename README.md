# MultiAgentCoding

**An AI-powered multi-agent coding control plane and visual execution environment.**

MultiAgentCoding is not simply a collection of AI agents. It is a **control plane
for designing, configuring, executing, observing, and managing AI coding
workflows** — a place where multiple AI agents, centralized orchestration,
reusable roles, a prompt library, visual workflow construction, model/provider
abstraction, BYOK connections, controlled execution, and persistent project
knowledge come together behind graphical and terminal interfaces.

---

## What is MultiAgentCoding?

The system combines:

- **Multiple AI agents** — seven identity-only agents (Matthew, Alex, Sarah,
  David, Elena, Max, Chloe) that are decoupled from any specific model.
- **Centralized orchestration** — a wave scheduler that runs workflow graphs
  with fan-in, fan-out, conditional routing, and bounded retry loops.
- **Reusable roles** — many-to-many role definitions (responsibilities, tools,
  permissions, rules, expected outputs) that are independent of models.
- **Reusable skills** — model/agent-independent operating procedures
  (ordered steps + capabilities) that sit between roles and prompts/workflows
  and compose into workflow nodes.
- **A Prompt Library** — reusable, role-typed prompt profiles that separate
  *what the AI should do* from *which model executes it*.
- **Evaluation** — reusable output rubrics (criteria dimensions, weighted
  scoring, pass/review/fail decisions) for judging agent/workflow output.
- **Visual workflow construction** — an executable graph designer where nodes
  are agent instances and edges carry success/failure conditions.
- **Model / provider abstraction** — a provider-neutral request/response layer
  with a planner, an executor, and provider adapters.
- **BYOK connections** — bring-your-own-key provider connections whose
  credentials never live inside workflow definitions.
- **Controlled execution** — planning before execution, explicit connection
  resolution, execution IDs, a runtime registry, timeouts, bounded retries,
  and dry-run previews.
- **Persistent project knowledge** — an Obsidian vault of architecture, tasks,
  agent context, decisions, and documentation.
- **Graphical monitoring and management** — an Obsidian-inspired Agent
  Dashboard, a workflow graph designer, and a retro terminal.

In short: it is a **control plane for designing, configuring, executing,
observing, and managing AI coding workflows**.

---

## Visual Experience

### Agent Dashboard (Web Dashboard)

The primary interface is a local, Obsidian-inspired **web dashboard** built on
FastAPI and served at `http://127.0.0.1:8790` (`launch_dashboard.bat`, or
`python -m scripts.web_ui.server`). It is a self-contained vanilla-JavaScript
frontend over the same backend used everywhere else.

- **Multi-agent panels** — the main area shows up to **six agent panels**,
  each displaying agent identity (tag + name), the **active model**, live
  **status**, current execution state, and a stop control. Panels are arranged
  in a 1/2/3/4/6 grid and are resizable via drag handles.
- **Master / agent views** — a **master** view coordinates all agents, while
  individual panels isolate a single agent's conversation and state.
- **Agent selection & visibility** — a visibility menu chooses which of the
  seven agents appear (max six); layout and selection persist across reloads.
- **Vault knowledge graph** — a read-only graph of the vault's wiki-links,
  colored by folder, with **section filter chips**, **zoom**,
  **pan**, a **minimap**, fullscreen/detach modes, and **level-of-detail (LOD)
  zoom bands** (zoomed out, only root/section/hub nodes keep their labels;
  leaf labels appear as you zoom in). A related-files list shows links and
  backlinks for the selected node, which can be sent as context to an agent.
- **Bottom bar** — four tabs: **Status** (live table of all agents), **Tasks**
  (inspect vault task nodes; assign an agent, set status, or run the real
  orchestrator dispatch), **Execution** (live task-run output), and **Logs**
  (agent / orchestrator log tails).

The dashboard reuses the backend unchanged: the in-process `RunHub` for agent
dispatch, `VaultBridge` / `ContextResolver` for vault reads and safe writes,
and the real Orchestrator CLI for task execution.

### Workflow Graph

Workflows are **executable graphs, not text instructions**. The **Agent
Workspace** (`/workspace`) is a visual workflow designer over the same
`Workflow` model and `workflow_engine` runtime:

- **Nodes** — each node is an *instance* of an agent (the same agent can
  appear many times, e.g. Developer #1 / #2 / #3), with its own model, roles,
  prompt profile, instructions, and BYOK connection. Drag an agent from the
  library onto the canvas to add a node.
- **Edges / dependencies** — draw edges between nodes; an edge is
  unconditional, `success`, or `failure`, which is what gives the graph its
  routing semantics (fan-in waits for all branches; conditional edges activate
  only the matching branch).
- **Graph navigation** — zoom in / out / fit-to-screen, plus a run legend that
  colors nodes by execution state (completed / running / waiting / failed /
  skipped / disabled).
- **Node properties** — a side panel configures model, connection, roles,
  prompt profile, and instructions, with deterministic prompt and model
  recommendations.
- **Execution relationships** — **Validate** checks the graph before running;
  **Dry Run** previews the ordered execution plan without dispatching any
  agent; **Run** starts a real run and reports per-node state live.
- **Templates & suggestions** — load a predefined template (sequential,
  parallel, reflection, planner-workers-reviewer, router, supervisor, and
  more) or generate a suggested workflow from repository analysis.

### ZOVA Terminal

A **retro / CRT-style terminal interface** (`python scripts/terminal_app.py`,
or `launch_terminal.bat`) provides a keyboard-oriented control surface as a
fallback when the graphical dashboard is not used. It features a pixel-art
**ZOVA** banner, a strict four-color phosphor scheme, a **tab bar** (MASTER +
one tab per agent, `F1`–`F7`), a model status bar, per-tab scrollable
consoles, and slash commands (`/tab`, `/cd`, `/status`, `/clear`, `/stop`,
`/help`, `/quit`) for agent dispatch, project operations, execution, and
status.

### Settings / Connections

The dashboard's **Settings** area manages the AI connection and runtime-model
surface:

- **AI Connections** in two modes — **Simple** (known providers such as
  Gemini, OpenAI, Anthropic: pick a provider and enter a key) and **Advanced**
  (custom / OpenCode-style providers: name, Base URL, key, auth method).
- **Per-agent configuration** — runtime models, modes, and fallback chains,
  with a spec ↔ `opencode.json` drift check.
- **Models & roles** — the model catalog, role creation, and many-to-many
  agent ↔ role assignment.

API keys are stored **only** in OpenCode's auth store
(`~/.local/share/opencode/auth.json`); the frontend only ever sees
`configured: true|false`.

---

## Core Architecture

The system is layered so that each concern is decoupled from the others:

```text
Agent Identity   (tag / name / key — no model, no role)
Role             (reusable behavior — many-to-many with agents)
Skill            (reusable operating procedure — steps + capabilities)
Prompt Profile   (reusable "what to do" instructions)
Workflow         (nodes = agent instances; edges = success/failure routing)
Evaluation       (reusable output rubric — criteria / scores / decision)
Model / Provider (runtime selection + BYOK connections)
Credential       (auth store only — never in a workflow)
Execution        (planner → executor → provider adapter → runtime)
```

The runtime control plane lives in `opencode.json` (agents, models, fallback);
the specs under `scripts/core/agents/` carry identity only. Any agent can run
on any user-selected model, and any role can be assigned to many agents
without editing an agent's module.

---

## Workflow Execution

A workflow moves through a single, well-defined execution pipeline:

```text
User
 │
 ▼
Visual / Terminal Interface
 │
 ▼
Workflow
 │
 ▼
Workflow Nodes
 │
 ▼
Execution Planner
 │
 ├── Model Resolution
 │
 ├── Connection Resolution
 │
 ├── Prompt Construction
 │
 └── Provider Adapter Selection
 │
 ▼
Executor
 │
 ▼
Provider Adapter
 │
 ▼
AI Model
 │
 ▼
Execution Runtime
 │
 ▼
Result / Logs / State
```

The **planner** (`scripts/core/execution/planner.py`) resolves each node before
it runs: the node's explicit model (else the agent's runtime model), the BYOK
connection (explicit wins; implicit degrades to the local OpenCode runtime),
the canonical prompt (roles + instruction/profile + workflow state), and the
provider adapter. The **executor** runs the planned node through the adapter
with a per-node **timeout** (default 300s), **cancellation**, and opt-in
bounded **retries**. The **runtime** (`scripts/core/execution/runtime.py`) owns
the in-memory run registry (start / get / cancel / snapshot). The **wave
scheduler** (`scripts/core/workflow_engine.py`) executes ready nodes
concurrently per wave, honors fan-in / conditional routing, and bounds retry
loops with `settings.max_iterations`.

Every run emits ordered execution events and per-node execution records that
appear in the run snapshot — no credentials are ever serialized into them.

---

## Prompt Library

Prompts are not scattered through agent and workflow code. They are reusable
**prompt profiles** — role-typed, versioned definitions of *what the AI should
do* (role, category, capabilities, prompt text). The library ships 49 built-in
profiles across 14 roles (software engineer, architect, code reviewer,
debugger, QA, security, DevOps, cloud, data, AI engineer, researcher,
technical writer, project manager, orchestrator). Profiles adapted from
external research carry provenance fields (`source`, `license`, `origin`) so
original and adapted profiles stay distinguishable.

A workflow node keeps its own editable `instructions` and may reference a
profile by id; the profile is the *source*, the instruction the *editable
result*. This is the separation between **what the AI should do** and **which
model executes it**:

```text
Prompt Library
      ↓
Prompt Profile
      ↓
Workflow Node
      ↓
Workflow Graph
      ↓
Execution Plan
      ↓
Model / Connection
      ↓
Provider Adapter
      ↓
Execution
```

The value: prompts become **reusable**, workflows become **composable**,
models become **replaceable**, providers become **interchangeable**, execution
becomes **observable**, and agents remain **model-independent**.

---

## Skills

A **Skill** (`scripts/core/skills.py`) is a lightweight, reusable *operating
procedure* that sits between a role and the prompt/workflow layer. Unlike a
prompt profile (a long "how to think" instruction), a skill is an **ordered
sequence of steps plus capabilities** — e.g. structured research, source
verification, anti-slop refinement, action-first communication, SEO research,
competitive analysis, security reconnaissance, security validation, the
fix→verify loop, repository analysis, and workflow planning. Skills are
model-independent, agent-independent, composable by id from workflow nodes,
and provenance-aware: skills adapted from external research carry
`source`/`license`/`origin` fields exactly like prompt profiles. Nothing here
introduces a runtime dependency on any external repository.

```text
Role → Skill → Prompt Profile / Workflow Node → Execution
```

---

## Evaluation

**Evaluation** (`scripts/core/evaluation.py`) is a native, reusable way to
judge agent or workflow output. An `EvaluationDefinition` declares ordered
criteria across a fixed dimension vocabulary (correctness, completeness,
quality, consistency, security, relevance, adherence); `evaluate()` turns
per-criterion 0–4 scores into a weighted total, a pass/review/fail decision,
and generated findings — deterministically, with no model, provider, or
credential involved. Definitions carry the same provenance metadata as prompt
profiles and skills, so evaluation patterns adapted from external research
(e.g. evidence-grounded security findings, cited research output) stay
traceable to their source.

---

## Agent Catalog (Categories → Presets → Empty Agent)

**Agent Catalog** (`scripts/core/agent_catalog.py`) is the deterministic
template layer between the reusable building blocks (Roles / Skills / Prompt
Profiles) and the 7 runtime agents. A hand-curated `AgentPreset` pins one role,
ordered skills, and prompt profile(s) under a high-level category (AI
Engineering, Research, Content/SEO, Software Development, DevOps/Cloud,
Security, QA/Testing) and references an existing agent key — it is **never**
synthesized from roles × prompts, so a category always shows exactly its
registered presets. A special **Empty Agent** (always first, independent of
every category) declares no role/skills/prompt/model/mode and therefore receives
only the raw user request. Selecting a preset populates
`Template → Preset → Model → Mode → Role → Skills → Prompt Profile`
deterministically; explicit customization still overrides preset defaults, and
suggestions never modify an explicitly configured agent. The existing 7 agents
are preserved as runtime identities (their `opencode.json` / `roles.json`
config is untouched).

---

## Runtime Context (Role → Skill → Prompt → Runtime)

The registries define Roles, Skills, and Prompt Profiles, but plain dispatch
only ever injected role assignments — so a multi-role agent still described
itself as a generic software engineer. `scripts/core/runtime_context.py` closes
that gap with **one deterministic builder** used by every execution path
(terminal RunHub, task Orchestrator, and workflow planner):

```text
Agent identity → Assigned roles → Skills → Prompt profile / instruction
             → Project context → Workflow context → Task → User request
```

Per-agent **skill** and **prompt-profile** assignments persist atomically in
`agent_context.json` at the repo root (`$ZOVA_AGENT_CONTEXT` overrides),
assignable via the Settings API (`PUT /api/settings/agents/{agent}/skills|prompts`).
Provenance (source/license/origin) is surfaced in the rendered context, and the
composition is ordered so task/user text can never overwrite system identity.
An agent with no roles, skills, profiles, or task context receives its raw
request unchanged — exactly as before.

---

## Multi-Agent Architecture

Seven roster agents — `matthew`, `alex`, `sarah`, `david`, `elena`, `max`,
`chloe` (tags `m1`…`m7`) — are deliberately **identity-only** (`tag`/`name`/
`key`). Model, role, and provider are *runtime* concerns resolved at dispatch
time, never pinned into the agent's spec. Dispatch is plain
(`opencode run --agent <a> -m <model> "<prompt>"`), and every agent carries a
de-duplicated fallback chain so a failed model fails over automatically.

Roles live in `roles.json` and are assigned many-to-many; changing an agent's
model never changes its roles, and vice versa. A `ProjectProfile` analyzer
derives technologies, manifests, instructions, and suggested roles from a
repository read-only — suggestions are never auto-applied.

---

## Model & Provider Architecture

The execution layer speaks a **provider-neutral** protocol:

- `ModelRequest` / `ModelResponse` — the request/response schemas (model id,
  prompt, optional sampling knobs, opaque metadata) with **no credential
  fields**.
- `ExecutionResult` / `ExecutionEvent` — per-node records and ordered events.
- The **planner** resolves model + connection + prompt + adapter.
- The **executor** enforces timeout, cancellation, and bounded retries.
- **Provider adapters** (`ProviderAdapter` protocol) consume the request and
  the resolved connection. The **OpenCode adapter** is the default runtime;
  future direct-provider adapters register themselves per provider.

Workflow logic never needs to know the internal API details of any provider.

A **Model Registry** catalogs models by provider and capability and ranks them
deterministically for a task/prompt. Runtime model resolution is separated
from the static definition of an agent: an agent's identity stays fixed while
its model is a configurable runtime value.

---

## BYOK

Bring-your-own-key connections are first-class, but **credentials are
separated from agents, prompts, roles, and workflow definitions**:

- A workflow node references a `connection_id` (or a model) — never a key.
- Connection **metadata** and the **credential** live in different stores;
  the public surface never returns a secret, and redaction scrubs secrets from
  error messages and logs.
- Explicit connection resolution is authoritative: a missing/invalid explicit
  connection fails loudly rather than silently substituting another one;
  implicit resolution degrades to the local OpenCode runtime.

The security model guarantees that **API keys are never embedded in workflow
definitions** and never serialized into events, snapshots, or responses.

---

## Ad-Supported Free AI Model Architecture

> **ساختار ارائه مدل‌های رایگان هوش مصنوعی مبتنی بر تبلیغات هوشمند**
> *(Architectural direction / future capability — not yet implemented.)*

A planned direction for funding free model access while keeping the
architecture clean:

```text
User
  ↓
AI Coding Environment
  ↓
Free AI Model Access
  ↓
Intelligent Advertising Layer
  ↓
Advertisement / Sponsor Revenue
  ↓
Model Usage Funding
```

The idea: users can access selected AI capabilities without directly paying
for every model request, while an **intelligent advertising layer** helps fund
model usage. The key architectural properties remain the ones already
established — the model/provider architecture stays separated from the
agent/workflow layer, paid BYOK providers coexist with free AI services, and
work can be routed according to availability, capability, and configuration:

```text
                    ┌──────────────────┐
                    │   AI Workflow    │
                    └────────┬─────────┘
                             │
                     Model Selection
                             │
             ┌───────────────┴───────────────┐
             │                               │
       Free AI Services                 BYOK Providers
             │                               │
   Ad-supported access             User-provided API key
             │                               │
             └───────────────┬───────────────┘
                             │
                     Provider Adapter
                             │
                         Execution
```

The free-service leg is labeled **future**; the BYOK leg and the provider
adapter boundary are **implemented today**.

---

## Key Innovations

### 1. Model-independent Agent Identity

Agents are not permanently tied to a model. The system separates:

```text
Agent Identity · Role · Prompt · Model · Provider · Connection · Credential · Execution
```

Because of this, agents can change models without changing their identity,
workflows remain portable, provider changes do not require rewriting agent
definitions, and runtime model selection becomes configurable.

### 2. Prompt Library as a reusable execution layer

Prompts are reusable execution instructions that can be combined with agent
identity, role, workflow state, node instructions, model selection, and
execution context — a separation between *what the AI should do* and *which
model executes it*.

### 3. Visual Workflow → Executable Workflow

```text
Visual Workflow
        ↓
Workflow Nodes
        ↓
Execution Planning
        ↓
Provider Resolution
        ↓
Provider Adapter
        ↓
Execution
        ↓
Runtime State
        ↓
Result / Observability
```

A workflow is drawn once and executed directly — the visual graph *is* the
execution structure, not a sketch beside it.

### 4. Provider-neutral execution architecture

`ModelRequest` / `ModelResponse` schemas, the planner, the executor, and the
adapter protocol give workflow logic a single neutral boundary; only the
adapter (currently OpenCode) knows provider specifics.

### 5. BYOK without coupling credentials to workflows

Credentials are separated from agents, prompts, roles, and workflow
definitions; API keys are never embedded in a workflow.

### 6. Intelligent model selection / runtime model resolution

The model registry and selection layer rank models deterministically for a
task/prompt, and runtime model resolution is separated from the static
definition of an agent.

### 7. Controlled execution

Planning before execution, explicit connection resolution, execution IDs, a
runtime registry, timeout handling, bounded retries, execution state, typed
errors, safe (secret-free) metadata, and dry-run previews. The guarantees are
deliberately modest — this is an execution control layer, not a sandbox.
The vault Orchestrator closes the loop end-to-end: a `ready` task node can be
assigned, dispatched (`--yes`; dry-run by default), and its status plus a
structured `## Agent Report` are written back into the node — inspectable via
`GET /api/tasks/{name}`.

### 8. Persistent AI project knowledge

The Obsidian vault keeps project knowledge — architecture, tasks, agent
context, and execution information — alongside the code rather than scattered
through prompts and logs.

### 9. Human + AI control plane

The system is designed so a human can configure agents, select models, define
workflows, inspect execution, approve/trigger work, inspect logs, manage
connections, and observe system state. It is a **visible and controllable AI
engineering environment**, not an opaque autonomous system.

---

## Persistent Project Knowledge

An Obsidian vault (`obsidian_vault/`) holds the project's persistent knowledge
as a linked, schema-validated graph (40 core nodes, including 4 seeded task nodes):

```text
Code
+
Project Knowledge
+
Architecture
+
Tasks
+
Agent Context
+
Execution Information
```

The vault is organized into numbered knowledge domains (`00-System` through
`06-Testing`) plus a large reusable prompt library and per-agent logs.
`VaultBridge` provides scoped, atomic, backed-up vault I/O; `ContextResolver`
performs bounded linked-context resolution from a node; `change_detector`
maps file changes to affected vault nodes; `knowledge_sync` checks docs ↔ code
drift; and `health_check` / `vault_validate` keep the vault schema-valid and
drift-free.

A separate **external knowledge / reference layer** (`knowledge/sources/`)
records the upstream repositories researched for MultiAgentCoding — their
license, purpose, useful patterns, and the integration decision — so adapted
prompts and workflow templates stay traceable to their source without making
the runtime depend on any external repository.

---

## Human + AI Control Plane

MultiAgentCoding keeps the human in the loop. The operator can:

1. **configure agents** (identity, runtime model, fallback),
2. **select models** per agent or per workflow node,
3. **define workflows** visually,
4. **inspect execution** through events, snapshots, and dry-run previews,
5. **approve / trigger work** (dispatch is explicit; orchestrator runs need
   `--yes`),
6. **inspect logs** for agents and the orchestrator,
7. **manage connections** (BYOK, validated but never echoing secrets),
8. **observe system state** through live panels, status, and the vault graph.

---

## Vision

The long-term goal is a **visual AI coding environment** where a developer can:

1. define agents
2. define reusable roles
3. select or create prompts
4. visually construct workflows
5. select execution models
6. connect external providers when desired
7. execute workflows
8. observe execution in real time
9. inspect results and logs
10. maintain persistent project knowledge

The system is progressing from **AI chat** toward an **AI engineering
workspace**, and from **single prompt → single model** toward **visual
workflow → multiple agents → multiple models/providers → controlled
execution**.

---

## Current Status

Implemented today: identity-only agent roster with runtime models and fallback;
reusable roles; the prompt library (49 profiles) with task classification and
recommendations; reusable skills (11 operating procedures) and evaluation
rubrics (3 built-in definitions); the model registry and selection; BYOK
connections with a secure credential store; the execution planner, executor,
and runtime with timeouts, cancellation, and bounded retries; the workflow
model, validation, templates, and dry-run; the deterministic **runtime-context
builder** that composes identity → roles → skills → prompt profiles → task into
one dispatch prompt on every execution path; the Obsidian vault stack; and
three interfaces — the Agent Dashboard, the workflow graph designer, and the
ZOVA terminal.

A real end-to-end task path is seeded in the vault: four task nodes in
`03-Tasks/` (`ready` / `planned` / `completed`) flow through assignment →
ContextResolver → Orchestrator → real agent execution → persisted status and
Agent Report, with `GET /api/tasks/{name}` returning the stored result.

Not yet implemented: direct (non-OpenCode) provider adapters, a persistent
run store, and the ad-supported free-model funding layer (an architectural
direction only).

---

## Roadmap

The history of what has been implemented — and what remains — is tracked in
[`obsidian_vault/Roadmap.md`](obsidian_vault/Roadmap.md) (phases from the
baseline reset, through the vault integration stack, the dashboard and
terminal, BYOK settings, and the agent/role/model decoupling).

---

## Repository Structure

```text
.
├── AGENTS.md              # Agent roster, workflow, fallback policy, conventions
├── opencode.json          # Runtime config: agents, models, providers, fallback
├── roles.json             # Reusable roles + many-to-many agent assignments
├── launch_agents.bat      # 7-window inbox launcher
├── launch_terminal.bat    # ZOVA retro terminal launcher
├── launch_dashboard.bat   # Agent Dashboard launcher (primary)
├── scripts/
│   ├── terminal_app.py    # ZOVA retro terminal entry point (thin shim)
│   ├── vault_validate.py  # Vault node schema validator
│   ├── generate_dashboard.py  # Regenerates the Dashboard's GENERATED block
│   ├── web_ui/            # Agent Dashboard + Workflow designer (FastAPI + vanilla JS)
│   │   ├── server.py      # App factory + uvicorn entry (--smoke)
│   │   ├── routes.py      # REST/SSE endpoints (thin layer over core)
│   │   ├── state.py       # WebState: drains HUB events into per-agent sessions
│   │   ├── graph.py       # VaultGraph: read-only node/edge model of the vault
│   │   ├── settings.py    # Settings facade: connections, keys, models
│   │   └── static/        # index.html · workspace.html · app.js · workspace.js …
│   ├── core/              # Decoupled engine
│   │   ├── agents/        # Per-agent identity (one AgentSpec module per agent)
│   │   ├── roles.py       # Reusable roles + many-to-many assignment
│   │   ├── project_profile.py  # Repository analysis → ProjectProfile + suggested roles
│   │   ├── run_hub.py     # Thread-safe multi-agent execution engine
│   │   ├── orchestrator.py    # Vault task dispatch (ready-gate, --yes, locks)
│   │   ├── vault_bridge.py    # Scoped vault I/O (atomic writes, backups)
│   │   ├── context_resolver.py  # Bounded linked-context resolution
│   │   ├── change_detector.py   # Snapshot diff → vault-node impact mapping
│   │   ├── knowledge_sync.py    # Docs ↔ code drift sync
│   │   ├── health_check.py      # Read-only vault/workspace checks
│   │   ├── opencode_cfg.py      # Runtime models single source of truth
│   │   ├── workflows.py         # Workflow model + persistence + validation + templates
│   │   ├── workflow_engine.py   # Wave scheduler + run lifecycle
│   │   ├── skills.py            # Reusable operating procedures + registry
│   │   ├── evaluation.py        # Output rubrics + weighted scoring + decisions
│   │   ├── runtime_context.py   # Deterministic runtime-prompt builder (identity → roles → skills → profiles → task)
│   │   ├── prompt_library/      # Prompt profiles + recommendations
│   │   ├── model_registry/      # Model catalog + selection
│   │   ├── model_connections/   # BYOK registry + resolver + credential store
│   │   ├── providers/           # ProviderAdapter protocol + OpenCode adapter
│   │   └── execution/           # schema · planner · executor · runtime · errors
│   └── ui/                # Terminal UI (palette, rendering, theme)
├── workflows/             # Persisted workflow JSON (one file per workflow)
├── knowledge/             # Project memory (ADRs, lessons, metrics, sources/)
└── obsidian_vault/        # Live vault: 00-System … 06-Testing + prompts + logs
```

---

## Development

- **Python 3.10+** (PEP 604 union hints) and the **OpenCode CLI**.
- Install: `python -m pip install -r requirements.txt` (runtime) and
  `-r requirements-dev.txt` (tests).
- Test suite: `pytest -q` (Python) — the Node graph/rendering tests run
  separately and are not part of the Python suite.
- Lint: `ruff check scripts/ test/`.

```bash
launch_dashboard.bat                   # Agent Dashboard (primary)
python scripts/terminal_app.py         # ZOVA retro terminal (fallback)
launch_agents.bat                      # 7-window inbox launcher
python -m scripts.core.orchestrator list          # vault task nodes
python scripts/vault_validate.py                  # vault schema check
python -m scripts.core.health_check               # read-only checks
```

---

## Architecture Documentation

See [`AGENTS.md`](AGENTS.md) for the complete control-plane documentation
(agent roster, fallback policy, workflow, and conventions), and
[`obsidian_vault/01-Architecture/`](obsidian_vault/01-Architecture/) for the
architecture map maintained in the vault.

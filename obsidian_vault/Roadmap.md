# Roadmap — MultiAgentCoding Control Plane

> **Last updated:** 2026-08-17 UTC
> **Current branch:** `feature/freebuff-byok-integration`
> This file documents the history actually implemented. The older swarm-era
> plan (role-swapping, self-evolve, archivist, web-app/GUI layers) was
> intentionally removed in the baseline-zero reset; the archive of that plan
> lives in root [`PLAN.md`](../PLAN.md) (ARCHIVED).

---

## Phase 0 — Baseline Zero (structural reset)

- [x] Agents reduced to plain identity + model (no roles, modes, or specialized prompts)
- [x] Removed swarm, self-evolve, archivist, analyzer, agent/prompt loggers, web app, desktop GUI
- [x] Plain dispatch: `opencode run --agent <a> -m <model> "<prompt>"`

## Phase 04–19 — Obsidian Vault Integration Stack

- [x] Vault structure + schema (`obsidian_vault/`, `scripts/vault_validate.py` — 36 nodes)
- [x] `vault_bridge.py` — scoped vault I/O, atomic writes, backups, change log
- [x] `orchestrator.py` — controlled dispatch (ready-gate, `--yes`, per-task locks, Agent-Report parsing)
- [x] `context_resolver.py` — bounded linked-context resolution
- [x] `change_detector.py` — snapshot diff → node impact (detection only)
- [x] `knowledge_sync.py` — docs ↔ code drift (dry-run by default, `check-conflicts`)
- [x] `generate_dashboard.py` — regenerates the Dashboard's GENERATED block
- [x] `health_check.py` — 11 read-only checks
- [x] End-to-end integration tests (`test/tests/test_e2e_integration.py`)

## Phase 20 — Agent Dashboard + ZOVA Terminal

- [x] `scripts/web_ui/` — Obsidian-inspired FastAPI dashboard (panels, vault graph, Status/Tasks/Execution/Logs)
- [x] `scripts/terminal_app.py` + `scripts/ui/` — ZOVA retro terminal (fallback interface)
- [x] 7-window inbox launcher (`launch_agents.bat` → `run_agent_worker.ps1/.sh`)

## Phase 25 — Settings / AI Connections (BYOK)

- [x] Settings UI with dual Simple / Advanced connection modes
- [x] Secure auth store integration (`~/.local/share/opencode/auth.json`; keys never returned to the frontend)
- [x] Per-agent model / mode / fallback editing with spec ↔ `opencode.json` drift check

## Phase 26 — Full Repository Audit & Repair

- [x] All 7 agents `mode: all` (subagent mode silently fell back to the default agent in `opencode run --agent`)
- [x] Fallback chains de-duplicated (no agent's own primary model in its chain)
- [x] Secret-bearing `opencode.json.bak` deleted; secrets scan clean
- [x] Docs reconciled: AGENTS.md, README.md, architecture map, knowledge README, skills, TASKS.json
- [x] Test suite green (426 unit tests OK, 1 skipped; JS tests 31 + 92 OK)

## Phase 27 — Agent / Role / Model decoupling

- [x] `AgentSpec` reduced to **identity only** (tag/name/key) — no model field
- [x] `opencode.json` is the single source of truth for runtime models
  (`opencode_cfg.resolve_model`); editing a model never rewrites a spec module
- [x] Reusable **roles** in `roles.json` (`scripts/core/roles.py`) — many-to-many,
  model-independent, composable into dispatch context
- [x] **Project Profile** analyzer (`scripts/core/project_profile.py`) —
  read-only repository analysis → technologies + suggested roles (never
  auto-applied)
- [x] Vault/architecture docs updated to describe models as runtime-configured,
  not identity-owned

---

## Phase 28 — External Agent Knowledge & Prompt Intelligence

Integrate useful knowledge, prompt patterns, skills, workflow patterns,
evaluation techniques, and architectural ideas from external repositories into
MultiAgentCoding — as research/reference sources, not runtime dependencies.

- [x] External source registry (`knowledge/sources/` + license matrix)
- [x] Source/license metadata (per-source records; exact licenses recorded)
- [x] Knowledge extraction (one research record per source)
- [x] Prompt extraction/adaptation (7 native profiles with provenance)
- [x] Skill extraction (11 native reusable Skills in `scripts/core/skills.py`,
  model/agent-independent, provenance-aware, composable into workflow nodes)
- [x] Workflow pattern extraction (`seo-research`, `security-audit` templates)
- [x] Evaluation pattern extraction (`scripts/core/evaluation.py` — criteria
  dimensions, weighted scoring, pass/review/fail decision, provenance)
- [x] Security workflow research (Strix find→validate→fix→re-scan→report loop)
- [x] Research/knowledge workflow research (open-notebook source/citation model)
- [x] Source attribution (`PromptProfile` provenance fields: source/license/origin)
- [x] Native MultiAgentCoding implementations (no copied external code)
- [x] Tests and validation (prompt provenance + template validation tests)

---

## Phase 29 — Real Task Execution & End-to-End Control Plane

- [x] Seeded real task nodes in `03-Tasks/` (`Task_Vault_Health_Check`,
  `Task_WebUI_Smoke_Test`, `Task_Docs_Audit`, `Task_Skill_Evaluation_Extraction`)
- [x] Reconciled vault task-status vocabulary with the Orchestrator
  (`planned`/`ready`/`in_progress`/`blocked`/`completed`/`failed`; legacy
  `todo`/`done` retired) so any dispatchable task also validates
- [x] Agent Report persisted into the task node (`## Agent Report` section)
  alongside the `## Execution Log` — results stay inspectable after a run
- [x] `GET /api/tasks/{name}` returns task detail + the persisted execution
  result (execution log + agent report), closing the Tasks → Run → Result loop
- [x] End-to-end path verified: vault task → assignment → ContextResolver →
  Orchestrator → real agent execution → status/result persistence
  (dry-run stays non-destructive; real Run requires `--yes`)
- [x] Tests: task execution (mock success/failure, locking, repeated-run guard,
  dry-run safety, report persistence), vault status validation, web API result
  retrieval

---

## Phase 30 — Runtime Context (Role → Skill → Prompt → Runtime data flow)

Close the gap between the registries and real dispatch: Roles / Skills /
Prompt Profiles were defined but plain dispatch only ever injected role
assignments, so a multi-role agent still described itself as a generic
software engineer. A single deterministic runtime-context builder now composes
one ordered prompt for every execution path.

- [x] `scripts/core/runtime_context.py` — canonical builder (identity → roles →
  skills → prompt profile/instruction → project → workflow → task → request),
  with per-agent skill/prompt-profile assignments persisted atomically to
  `agent_context.json` (override `$ZOVA_AGENT_CONTEXT`)
- [x] RunHub (terminal) and Orchestrator (task dispatch) both compose through
  the builder — role/skill/profile info actually reaches the runtime prompt
- [x] `planner.build_node_prompt` delegates to the same builder, so workflow
  nodes inherit agent skills when unset and override them per-node
- [x] Web UI Settings API exposes per-agent skill + prompt-profile assignment
  (`GET/PUT /api/settings/agents/{agent}/skills|prompts`), plus `GET
  /api/settings/skills` and `/api/settings/prompt-profiles` pickers
- [x] Deterministic composition order documented; task/user text can never
  overwrite system-level identity (identity is rendered first, request last)
- [x] Provenance preserved (skills/profiles surface source/license/origin)
- [x] Role → Skill and Role → Prompt Profile resolution from the effective
  repository taxonomy (union, deduplicated); explicit agent/node values win
- [x] `roles.json` gains `researcher`, `seo-researcher`, `seo-writer` so the
  researcher/SEO roles the library already supports are first-class
- [x] Settings API exposes role-derived vs explicit ids
  (`role_derived_skill_ids` / `role_derived_prompt_profile_ids`)
- [x] Backward compatible: an unconfigured agent receives its raw request
  unchanged; existing workflows/agents/tasks keep validating
- [x] Tests: `test_runtime_context.py` (self-description bug repro, role/skill/
  profile injection, composition order, empty-agent compatibility, workflow
  skill inheritance, no-secret exposure, automatic role derivation + override +
  multi-role union + unknown/unmapped role) + web UI assignment API tests

---

## Phases A–H — Repository-Driven Taxonomy Migration

- [x] Structured repository evidence, native skill source, declared role
  relations, and original/internal capability evidence
- [x] Deterministic generated taxonomy plus durable curated overrides and
  integrity checks (staleness, references, effective consistency, coverage)
- [x] Effective taxonomy wired into runtime resolution, all-agent coverage,
  Agent Catalog, Taxonomy API, and the Dashboard Taxonomy interface
- [x] Compatibility migration from `agent_context.json` into taxonomy overrides
  without deleting user data; dispatch never auto-rebuilds taxonomy
- [x] Documentation/status reconciliation and taxonomy architecture record:
  `docs/architecture/repository-driven-agent-taxonomy.md`

---

## Backlog / Future

- [x] Added `Component_*` nodes for orchestrator/vault_bridge/context_resolver/change_detector/knowledge_sync (Dashboard O2 gaps resolved)
- [ ] Model-fallback tuning once free-tier quota stabilizes (observe `~/.config/opencode/opencode-model-fallback.log`)
- [ ] Knowledge re-indexing automation

## Audit Status

- **Last full audit:** 2026-08-12 (see root `implementation_audit.md`, `project_audit.md`, and this repository's current test/validation state)
- **Branch:** `feature/freebuff-byok-integration`

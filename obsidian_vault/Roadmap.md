# Roadmap — MultiAgentCoding Control Plane

> **Last updated:** 2026-08-12 UTC
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

---

## Backlog / Future

- [ ] Seed real task nodes in `03-Tasks/` and drive them through the Orchestrator end-to-end
- [ ] Add `Component_*` nodes for orchestrator/vault_bridge/context_resolver/change_detector/knowledge_sync (zero the Dashboard known-gaps list)
- [ ] Model-fallback tuning once free-tier quota stabilizes (observe `~/.config/opencode/opencode-model-fallback.log`)
- [ ] Knowledge re-indexing automation

## Audit Status

- **Last full audit:** 2026-08-12 (see root `implementation_audit.md`, `project_audit.md`, and this repository's current test/validation state)
- **Branch:** `feature/freebuff-byok-integration`

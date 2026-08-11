# implementation_audit.md — Roadmap vs. Actual Implementation

> **FINAL AUDIT** — read-only. No project files were modified, created, renamed,
> or deleted by this audit. The only artifact my verification produced was a
> stray `test/state.md` (created by running the suite from `test/`), which was
> removed again; the working tree is exactly as found.
>
> **Audit run:** 2026-08-11 · **Branch:** `full-branch` · **HEAD:** `d0503d0`

---

## 0. Executive Summary

The codebase implements a **complete Obsidian-Agent integration stack** on top
of the baseline-zero 7-agent control plane. This is real, tested, and green:
**327 unit tests pass (1 skipped)** from the repo root, the vault validates
(36 schema-valid nodes), agent specs are in sync with `opencode.json`, and the
Obsidian desktop app is now installed with this folder opened as a live vault.

However, the **documentation layer did not keep up**:

- `obsidian_vault/Roadmap.md` still describes the **old swarm-era plan**
  (Phase Zero + A–F), claims branch `baseline-zero`, and does not mention the
  20-phase Obsidian architecture that was actually built.
- The **20-phase plan itself is not archived anywhere** in the repo — it was
  delivered as ephemeral "MASTER PLAN — Analyzer Core" prompts (see agent logs).
  Only phase numbers embedded in source comments (`Phase 04/12/15/16/17/18/19`)
  and `project_audit.md` ("Step [01/20]") prove it existed.
- `AGENTS.md`, `README.md`, `docs/architecture/Architecture.md`, and the vault's
  own `System_Architecture.md` / `Architecture_Overview.md` still describe
  "baseline-zero, no external integrations" — and `System_Architecture.md`
  even lists `vault_bridge.py` as **[P] Planned**, when it is implemented,
  tested, and in use (Phase 12).

Bottom line: **the implementation is ahead of the documentation.**

---

## 1. Repository & Git State

| Item | Status | Evidence |
|---|---|---|
| Branch | `full-branch` | `git branch --show-current` |
| Remote sync | up to date with `origin/full-branch` | `git status` |
| HEAD | `d0503d0 feat: complete full obsidian integration and multi-agent structure` | `git log` |
| Working tree | 3 modified files, **all runtime/user artifacts** | `git status --short` |
| Uncommitted source changes | **none** | — |

Modified files (not source, no action needed):

```
 M obsidian_vault/.obsidian/graph.json    ← user opened vault in Obsidian (22:40)
 M obsidian_vault/.obsidian/workspace.json← Obsidian window state
 M state.md                               ← runtime session state (auto-written by StateTracker)
```

---

## 2. Component-by-Component Verification

Legend: ✅ IMPLEMENTED · ⚠️ PARTIAL · ❌ MISSING · 🗑️ REMOVED · ❓ UNKNOWN

| # | Component | Verdict | Evidence (source / tests / run) |
|---|---|---|---|
| 1 | **Agent architecture** | ✅ | 7 `AgentSpec` modules (`scripts/core/agents/`) + `master.py`, `registry.py` derives roster/tabs, `__main__.py` CLI. `python -m scripts.core.agents verify` → `OK: 7 agent specs in sync with opencode.json`. Tested (`test_agents.py`, `test_agent_specs.py`). |
| 2 | **Orchestrator** | ✅ (infra) ⚠️ (usage) | `scripts/core/orchestrator.py`: `list/show/set-status/dispatch/report/context`, status transition machine, ready-gate, dry-run vs `--yes`, per-task atomic locks, scope-drift detection, Agent-Report parsing, execution-log writes. Tested (`test_orchestrator.py`, `test_controlled_execution.py`, E2E). **But `03-Tasks/` contains zero real task nodes** — `orchestrator list` → `No task nodes found`. Infrastructure works and is fully tested; nothing has been dispatched for real yet. |
| 3 | **Obsidian/Vault integration** | ✅ | `scripts/core/vault_bridge.py` (Phase 12): path validation, scoped reads, strict frontmatter, atomic writes (temp+`os.replace`), timestamped backups, JSONL change log, duplicate-execution guard. Vault: 7 sections (00–06) + `System_Core` root + hubs, 36 nodes. `python scripts/vault_validate.py` → `VAULT VALIDATION OK — 36 node(s)`. **Obsidian desktop app is installed** (`%LOCALAPPDATA%\Programs\obsidian`) and `.obsidian/` config dir exists — the vault is now a live Obsidian vault, not just static Markdown. |
| 4 | **Obsidian WikiLink system** | ✅ | `[[...]]` regex (`LINK_RE`) parsing + resolution in `vault_bridge`, `context_resolver`, `health_check`, `change_detector`, `vault_validate`, `generate_dashboard`. Broken-link detection, cycle detection, orphan checks all tested. Rendering is native (Obsidian app). |
| 5 | **Task management** | ⚠️ PARTIAL | Full machinery exists and is tested: task schema (`_TASK_TEMPLATE`), statuses (`planned/ready/in_progress/blocked/completed/failed`), `Tasks_Home`, `Task_Backlog`, transition validation, locks, dedupe. **No tasks have ever been created** — `Task_Backlog` shows "*(none yet)*", Dashboard counts are all `0`. The loop is proven only against temp vaults in tests. |
| 6 | **Context Resolver** | ✅ | `scripts/core/context_resolver.py`: bounded BFS from a task node, depth/node caps, direct-dependency priority, type filtering beyond depth 1, cycle detection + reporting, unresolved-link tracking, deterministic, JSONL logging. Tested (`test_context_resolver.py`, E2E). |
| 7 | **Controlled Agent Execution** | ✅ | Ready-gate, `is_dispatchable`, explicit `--yes` authorization, per-task O_EXCL locks, transition enforcement, scope-drift detection, mandatory structured `## Agent Report` parsing, `completed/blocked/failed` decision matrix, no-delete guarantee, atomic status write-back with execution log. Tested (`test_controlled_execution.py` — 7 test classes, E2E). |
| 8 | **File/change detection** | ✅ | `scripts/core/change_detector.py` (Phase 15): snapshot diff (mtime_ns + sha256), created/modified/renamed/deleted, path classification, cross-impact mapping to vault nodes, dedupe keys, temp/editor-file exclusion, **detection-only (never executes agents)**. Tested (`test_change_detector.py`). |
| 9 | **Code ↔ Obsidian synchronization** | ✅ | `scripts/core/knowledge_sync.py` (Phase 16): dry-run by default, `--apply` only for managed fields (`updated`/`status`/`related_component`) and `<!-- GENERATED -->` blocks; `check-conflicts` reports docs↔code drift both directions without fixing; JSONL sync log. Tested (`test_knowledge_sync.py`). **Known gap acknowledged in Dashboard:** 5 real modules have no `Component_*` node yet (orchestrator, vault_bridge, context_resolver, change_detector, knowledge_sync). |
| 10 | **Dashboard** | ✅ | `scripts/generate_dashboard.py` (Phase 17): rewrites only the `GENERATED` block, verifies every WikiLink against real nodes, atomic write, `--check` freshness gate. `obsidian_vault/Dashboard.md` is schema-valid and up to date. Tested (`test_generate_dashboard.py`, E2E). Cosmetic wart: "Recent Changes" rows show temp-path entries from test runs. |
| 11 | **Graph health checks** | ✅ | `scripts/core/health_check.py` (Phase 18): 11 read-only checks (frontmatter, broken links, task statuses, agent refs, orphans, duplicates, cycles, reachability from `System_Core`, hub consistency, docs-vs-code drift, legacy files), JSON/print report, JSONL log, exit 1 on errors. Tested (`test_health_check.py`). E2E asserts health checks introduce no new errors. |
| 12 | **End-to-end tests** | ✅ | `test/tests/test_e2e_integration.py` (Phase 19): full workflow (task → orchestrator → resolver → mock agent → status write-back → dashboard) on temp vaults, with a workspace-manifest sha256 gate proving the real `scripts/`, `test/`, and vault are untouched. **Full suite: 327 tests OK, 1 skipped** (`python -m unittest discover -s test/tests` from repo root). |
| 13 | **Roadmap accuracy** | ❌ STALE | See §4. |
| 14 | **Git branch / working tree** | ✅ | Clean and coherent — see §1. |

**Verification note (suite launch quirk):** the suite passes **only from the
repo root**. Running `python -m unittest discover -s tests` from inside `test/`
fails with 6 import errors (`ModuleNotFoundError: No module named 'scripts.core'`)
because `test_e2e_integration.py` imports the core package. This is a known
ergonomics gap, not a test failure.

---

## 3. The 20-Phase Obsidian-Agent Plan — Completion Status

The plan document **does not exist in the repository**. It was delivered as
typed prompts (the "MASTER PLAN — Analyzer Core (mandatory, pre-dispatch) ·
PHASE 1 · REQUIREMENTS…" lines visible in `obsidian_vault/agents_logs/M7_Chloe.md`,
truncated in the logs). What survives are phase markers in source comments plus
`project_audit.md` ("Step [01/20] deliverable"). Status below is reconstructed
from those markers + the presence of the deliverable modules + test evidence.

| Phase | Marker / deliverable | Status |
|---|---|---|
| 01 | `project_audit.md` — "Step [01/20] deliverable" | ✅ completed |
| 02 | Vault↔control-plane wiring / vault creation (`System_Architecture.md` cites "project plan Phase 02") | ✅ completed |
| 03 | *(no marker; vault structure/task schema precursor)* | ❓ no evidence |
| 04 | `scripts/vault_validate.py` — node schema validator | ✅ completed |
| 05–10 | *(no markers; intermediate wiring: frontmatter schema, agent nodes, hubs — all present in vault)* | ❓ no markers, deliverables present |
| 11 | Orchestrator core (in "Modules added in Phases 11–16" per `generate_dashboard.py`) | ✅ completed |
| 12 | `scripts/core/vault_bridge.py` — "Guarantees (see the Phase 12 plan)" | ✅ completed |
| 13–14 | Context resolver / dispatch plumbing (in "Phases 11–16" span) | ✅ completed (by span) |
| 15 | `scripts/core/change_detector.py` — "Design (Phase 15)" | ✅ completed |
| 16 | `scripts/core/knowledge_sync.py` — "Sources of truth (Phase 16)" | ✅ completed |
| 17 | `scripts/generate_dashboard.py` — "Safety (Phase 17)" | ✅ completed |
| 18 | `scripts/core/health_check.py` — "Detection-only (Phase 18)" | ✅ completed |
| 19 | `test/tests/test_e2e_integration.py` — "End-to-end integration tests (Phase 19)" | ✅ completed (327 tests OK) |
| 20 | Final audit — this document | 🔄 in progress |

**Genuinely completed:** Phases 01, 02, 04, 11, 12, 15, 16, 17, 18, 19
(demonstrable from code markers + deliverables + green tests). Phases 03,
05–10, 13–14 have no in-code markers; the artifacts they would have produced
(vault sections, hubs, resolver) exist, so they are *likely* done but cannot be
proven from the codebase alone.

---

## 4. Conflicts Between Roadmap / Docs and the Actual Implementation

1. **`obsidian_vault/Roadmap.md` is the wrong plan.** It documents the old
   swarm-era roadmap (Phase Zero + Phase A–F), states *"Current branch:
   `baseline-zero`"* (actual: `full-branch`), and lists the removed swarm
   architecture (Phases A–C) as done. It contains **no trace of the 20-phase
   Obsidian architecture** that was actually built.
2. **Roadmap Phase E (security BLOCKER) is already resolved.** It demands
   removing the `9router` API key from `opencode.json` — the current file has
   no `9router` block (only `ollama` + `mulerouter`), and `agents verify`
   confirms the roster is clean. (The `.bak` file still holds the old key but
   is gitignored.)
3. **Roadmap Phase D slash commands are trimmed.** It lists
   `/help /cd /model /mode /agents /status /clear /stop /swarm /proposals
   /evolve /quit`; the actual `command_parser.py` help shows only
   `/tab /help /cd /status /clear /stop /theme /quit`.
4. **`System_Architecture.md` marks `vault_bridge.py` as `[P] Planned`** — it
   is implemented, tested, and wired (Phase 12). Also, the new components
   (orchestrator, vault_bridge, context_resolver, change_detector,
   knowledge_sync, health_check, generate_dashboard) have **no `Component_*`
   nodes** at all — the architecture map predates them. The Dashboard honestly
   lists this as a known gap.
5. **`AGENTS.md`, `README.md`, `docs/architecture/Architecture.md`,
   `Architecture_Overview.md` all say "baseline-zero: no external
   integrations"** — contradicted by the implemented Obsidian stack. They are
   stale, not wrong-about-agents: the agent contract itself is unchanged
   (still plain 7-agent dispatch).
6. **`obsidian_vault/06-Testing/Test_Report_Suite.md` reports "201 tests"**
   (verified 16:35); the suite is now **327 tests**. Stale count.
7. **Vault Roadmap's "Audit Status" block** references branch
   `feature/obsidian-vault-integration` and dates from 2026-08-10 — superseded
   by `full-branch` and the 2026-08-11 work.

---

## 5. Removed Components (from git history)

Verified via `git log --diff-filter=D`:

**Commit `d0503d0` (HEAD — the Obsidian integration commit) deleted:**
`scripts/agent_logger.py`, `scripts/core/agent_definitions.py`,
`scripts/core/agents/models.py`, `scripts/core/analyzer.py`,
`scripts/core/archivist.py`, `scripts/core/config.py`,
`scripts/core/intent_classifier.py`, `scripts/core/self_evolve_bridge.py`,
`scripts/intent_router.py`, `scripts/obsidian_auditor.py`,
`scripts/prompt_logger.py`, `scripts/self_evolve.py`, `scripts/swarm.py`,
`scripts/ui/settings_modal.py`, `scripts/web_app.py`, `launch_web.bat`, and
tests `test_analyzer.py`, `test_archivist.py`, `test_intent_router.py`,
`test_self_evolve.py`, `test_swarm.py`, `test_web_app.py`.

**Earlier commit `eb1158b` ("purge web/GUI to pure CLI") deleted:**
`scripts/web_app.py`, `scripts/unified_app.py`, `scripts/supervisor.py`,
`scripts/restart_web.ps1`, `launch_web.bat` + their tests.

**Documented removals:** root `PLAN.md` is explicitly **ARCHIVED** and records
the removed swarm / self-evolve / archivist / web-dashboard design as history.
The `9router` provider block (embedded API key) was removed from
`opencode.json`; the gitignored `opencode.json.bak` still contains it (per
`project_audit.md`) — a lingering hygiene item.

All of these were **intentional** (baseline-zero reset, then a deliberate
rebuild via the Obsidian stack). None are missing by accident.

---

## 6. What Should Be Kept / Built Next / Recommended Phase

### A. What is actually working
- **7-agent control plane**: specs, registry, CLI, dispatch (`opencode run`),
  in sync with `opencode.json`, launchers, ZOVA terminal.
- **Full Obsidian integration stack**: vault (36 valid nodes, live Obsidian
  vault), validator, VaultBridge, Orchestrator (controlled dispatch), Context
  Resolver, ChangeDetector, KnowledgeSync, Dashboard generator, HealthCheck.
- **WikiLink graph system** parsed/resolved/checked across 6 modules.
- **Test suite: 327 tests OK (1 skipped)** from the repo root, including the
  Phase-19 E2E workflow with workspace-untouched verification.
- **Git hygiene**: clean source tree, secrets out of tracked files, runtime
  artifacts gitignored.

### B. What is missing
- **Zero real tasks in the vault** — the Orchestrator has never dispatched a
  real task; its proven behavior is test-only. The system is a fully built,
  fully tested **capability** with no production workload yet.
- **Component nodes for the new modules** — 5 modules lack `Component_*` nodes
  (orchestrator, vault_bridge, context_resolver, change_detector,
  knowledge_sync); the architecture map doesn't cover the Obsidian stack.
- **The 20-phase plan document itself** — never archived; only reconstructable
  from code markers. A canonical plan file would prevent this drift recurring.
- **Stale docs** — Roadmap, AGENTS.md, README, docs/architecture, vault
  architecture map, Test_Report_Suite count (201 → 327).
- **Suite launch ergonomics** — running tests from `test/` cwd fails with
  import errors; only the repo-root invocation works.
- **`opencode.json.bak`** still holds the old hardcoded key (gitignored but
  should be scrubbed/deleted).

### C. What was removed
- Web app, desktop GUI, supervisor/restart machinery, prompt/agent loggers,
  intent router, self-evolve engine, swarm coordinator (+ their tests),
  analyzer/archivist/auditor modules, `settings_modal.py`, `launch_web.bat`.
- The `9router` secret block from `opencode.json`.
- (All intentional — see §5.)

### D. What should be kept
- **The Obsidian stack** (bridge / orchestrator / resolver / sync / dashboard /
  health) — it is well-designed, safety-first (dry-run, locks, backups, atomic
  writes, no-false-documentation), and thoroughly tested. Keep as-is.
- **Controlled-execution guarantees** (ready-gate, `--yes`, per-task locks,
  scope-drift detection) — the strongest part of the design.
- **Agent-specs-as-source-of-truth** pattern and `verify` drift check.
- **The honest-drift reporting** (check-conflicts + Dashboard known-gaps list).

### E. What should be built next
1. **Create the first real task nodes** in `03-Tasks/` and run one real
   orchestrator dispatch end-to-end (proves the loop outside temp vaults).
2. **Add `Component_*` nodes** for the 5 unmapped modules (orchestrator,
   vault_bridge, context_resolver, change_detector, knowledge_sync) and update
   the architecture map — this also exercises KnowledgeSync's conflict
   checker to zero.
3. **Archive the 20-phase plan** as a canonical document (e.g. `PLAN.md` or a
   vault node) with checkboxes, so future audits have a source of truth.
4. **Fix the test-launch path** (root-relative imports or a `conftest`-style
   sys.path shim) so `cd test && python -m unittest discover` also works.
5. **Scrub/delete `opencode.json.bak`** (contains the old API key).

### F. Recommended next phase
**"Phase 21 — Operationalize + Reconcile Docs":**
1. Seed 2–3 real tasks in `03-Tasks/` and drive them through the Orchestrator
   (real dispatch, real status transitions, real dashboard updates).
2. Reconcile the documentation layer in one pass: rewrite `Roadmap.md` to the
   actual 20-phase history + current state, update `AGENTS.md` / `README.md` /
   `docs/architecture/Architecture.md` / `System_Architecture.md` to cover the
   Obsidian stack, add the missing `Component_*` nodes, and fix the
   `Test_Report_Suite` count.
3. Archive the reconstructed 20-phase plan as a permanent vault node.
4. Re-run `health_check` + `knowledge_sync check-conflicts` until zero errors
   and zero drift, then commit.

---

*End of audit. Report produced as requested — no implementation performed.*

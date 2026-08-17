# Component Node Audit

**Date:** 2026-08-17  
**Scope:** audit only; no Vault nodes were created or modified  
**Decision target:** the `Component_*` backlog item in `obsidian_vault/Roadmap.md`
and `TASKS.json` (`O2`)

## Executive conclusion

The implementation backlog requires exactly five new architecture nodes:

1. `Component_Orchestrator`
2. `Component_VaultBridge`
3. `Component_ContextResolver`
4. `Component_ChangeDetector`
5. `Component_KnowledgeSync`

These five are real, implemented subsystems, are named explicitly by the
Roadmap backlog, and are also the five hard-coded gaps shown by the generated
Dashboard. They should be created in a later implementation phase.

`health_check.py` currently reports ten additional top-level modules. Those
warnings are produced by a filename-to-node heuristic in
`knowledge_sync.check_conflicts`, not by unresolved WikiLinks or a runtime
failure. They identify broader architecture-documentation debt, but they are
not part of the current Roadmap item and should not trigger ten module-shaped
nodes during O2.

## Evidence and audit method

The audit compared:

- `obsidian_vault/Roadmap.md`, especially Phases 04–19 and Backlog / Future;
- `TASKS.json`, task `O2`;
- `obsidian_vault/00-System/Node_Schema_Reference.md`;
- the five existing nodes under `obsidian_vault/01-Architecture/Component_*.md`;
- `Architecture_Home`, `System_Architecture`, `Architecture_Overview`, and the
  generated Dashboard;
- `scripts/core/health_check.py::check_conflicts` and
  `scripts/core/knowledge_sync.py::{find_component_node,check_conflicts}`;
- the relevant core modules, their imports, and their focused tests.

The canonical candidate id follows the existing KnowledgeSync conversion:
snake-case module name → CamelCase → `Component_<CamelCase>`. For example,
`vault_bridge.py` maps to `Component_VaultBridge`.

## Existing component coverage

The Vault currently contains five component nodes:

| Existing node | Backing implementation | Coverage assessment |
|---|---|---|
| `Component_Terminal` | `scripts/terminal_app.py`, `scripts/ui/` | Current terminal UI |
| `Component_RunHub` | `scripts/core/run_hub.py` | Live plain agent dispatch and telemetry |
| `Component_AgentSpecs` | `scripts/core/agents/` | Agent identity/roster and config verification boundary |
| `Component_StateTracker` | `scripts/core/state_tracker.py` | `state.md` persistence |
| `Component_Launchers` | launchers and inbox workers | Process startup and inbox execution |

None of these covers the five Vault-stack subsystems closely enough to replace
their missing nodes. In particular, `Component_RunHub` is not the task
Orchestrator: RunHub manages interactive live agent processes, while the
Orchestrator owns Vault task lifecycle, authorization, locking, bounded
context, and result persistence.

## Exact Roadmap-required nodes

### `Component_Orchestrator`

- **Name:** Orchestrator
- **Responsibility:** coordinate executable Vault task nodes; enforce the
  `ready` gate and legal transitions; require explicit `--yes`; acquire a
  per-task lock; compose bounded runtime context; dispatch through the shared
  OpenCode command boundary; parse `Agent Report`; persist execution outcome.
- **Related files/modules:** `scripts/core/orchestrator.py`; indirect shared
  execution helpers in `scripts/core/run_hub.py` and
  `scripts/core/providers/opencode.py`; task-facing routes in
  `scripts/web_ui/routes.py`.
- **Related agents:** all seven roster agents through `Agents_Home`; the
  assigned agent is resolved dynamically, so the component must not be tied
  to one agent identity.
- **Dependencies:** `Component_VaultBridge`, `Component_ContextResolver`,
  `Component_RunHub`, `Component_AgentSpecs`; runtime configuration/context
  services in `opencode_cfg.py`, `roles.py`, and `runtime_context.py`.
- **Status:** `active` (`type: architecture`, `owner: architect`).
- **Links:** parent `System_Architecture`; related
  `Component_VaultBridge`, `Component_ContextResolver`, `Component_RunHub`,
  `Component_AgentSpecs`, `Tasks_Home`, and `Agents_Home`.
- **Evidence:** Roadmap Phase 04–19 marks controlled dispatch complete and the
  backlog names `orchestrator`; `TASKS.json/O2` repeats it; focused behavior is
  covered by `test_orchestrator.py`, `test_controlled_execution.py`,
  `test_task_execution.py`, and `test_e2e_integration.py`.

### `Component_VaultBridge`

- **Name:** Vault Bridge
- **Responsibility:** provide the safe Vault I/O boundary: validate Vault
  paths, parse nodes/frontmatter, resolve task relationships, make scoped and
  atomic managed-field updates, create/prune backups, log changes, and prevent
  invalid/repeated dispatch.
- **Related files/modules:** `scripts/core/vault_bridge.py`.
- **Related agents:** no direct agent ownership; all roster agents are indirect
  consumers through the Orchestrator. Link `Agents_Home`, not seven individual
  agent nodes.
- **Dependencies:** Python standard library and Vault schema; it is the bottom
  of the Vault-I/O stack and must not depend on the Orchestrator.
- **Status:** `active` (`type: architecture`, `owner: architect`).
- **Links:** parent `System_Architecture`; related
  `Component_Orchestrator`, `Component_ContextResolver`,
  `Component_KnowledgeSync`, `Tasks_Home`, and `Node_Schema_Reference`.
- **Evidence:** Roadmap Phase 04–19 describes atomic Vault I/O, backups, and
  change logs; both the Roadmap backlog and `TASKS.json/O2` name
  `vault_bridge`; `test_vault_bridge.py`, `test_path_traversal.py`, and the
  Orchestrator tests exercise the boundary.

### `Component_ContextResolver`

- **Name:** Context Resolver
- **Responsibility:** resolve a task's WikiLink graph into a deterministic,
  typed, bounded `ContextPackage`; prioritize direct dependencies, enforce
  depth/node caps, detect cycles/unresolved links, and log the resolution.
- **Related files/modules:** `scripts/core/context_resolver.py`.
- **Related agents:** all dynamically assigned agents receive its output via
  the Orchestrator; no single roster agent owns it.
- **Dependencies:** `Component_VaultBridge` for safe node reads and task
  resolution.
- **Status:** `active` (`type: architecture`, `owner: architect`).
- **Links:** parent `System_Architecture`; related
  `Component_Orchestrator`, `Component_VaultBridge`, `Tasks_Home`, and
  `Agents_Home`.
- **Evidence:** Roadmap Phase 04–19 and `TASKS.json/O2`; direct tests in
  `test_context_resolver.py` plus traversal and E2E coverage.

### `Component_ChangeDetector`

- **Name:** Change Detector
- **Responsibility:** snapshot the project/Vault, deterministically classify
  created/modified/renamed/deleted paths, deduplicate detections, and map
  changes to affected Vault/component nodes. It is detection-only and must
  never trigger agents or modify user files.
- **Related files/modules:** `scripts/core/change_detector.py`.
- **Related agents:** none directly; findings may inform operators or future
  tasks, but detection never dispatches an agent.
- **Dependencies:** Python standard library, repository/Vault read access, and
  the existing component-link convention; no runtime dependency on the
  Orchestrator.
- **Status:** `active` (`type: architecture`, `owner: architect`).
- **Links:** parent `System_Architecture`; related
  `Component_KnowledgeSync`, `Component_VaultBridge`, `Architecture_Home`, and
  `Documentation_Home`.
- **Evidence:** Roadmap Phase 04–19 and backlog; `TASKS.json/O2`;
  `test_change_detector.py` and `test_e2e_integration.py` explicitly verify
  detection-only behavior and impact mapping.

### `Component_KnowledgeSync`

- **Name:** Knowledge Sync
- **Responsibility:** compare code and Vault documentation, build a dry-run
  synchronization plan, restrict writes to managed fields/generated blocks,
  detect component/source drift, and log sync runs. Code remains read-only.
- **Related files/modules:** `scripts/core/knowledge_sync.py`; its conflict
  output is consumed by `scripts/core/health_check.py`.
- **Related agents:** none directly; it is an operator/maintenance service and
  does not dispatch agents.
- **Dependencies:** `Component_VaultBridge` for safe managed writes and
  schema-aware reads; component naming/link conventions for impact mapping.
- **Status:** `active` (`type: architecture`, `owner: architect`).
- **Links:** parent `System_Architecture`; related
  `Component_VaultBridge`, `Component_ChangeDetector`, `Architecture_Home`,
  `Documentation_Home`, and `Node_Schema_Reference`.
- **Evidence:** Roadmap Phase 04–19 and backlog; `TASKS.json/O2`;
  `test_knowledge_sync.py`, `test_health_check.py`, and E2E tests verify
  dry-run safety, conflict detection, and code read-only behavior.

## Health-check warning inventory

`knowledge_sync.check_conflicts` scans every top-level `scripts/core/*.py`
except `__init__.py`, `progress.py`, `state_tracker.py`, and
`command_parser.py`. It emits a warning whenever the module filename does not
map to a same-named `Component_*` node. `health_check` merely wraps those
strings as `docs-code` warnings.

| Missing candidate id | Module | Classification |
|---|---|---|
| `Component_Orchestrator` | `orchestrator.py` | Genuine missing node; required now |
| `Component_VaultBridge` | `vault_bridge.py` | Genuine missing node; required now |
| `Component_ContextResolver` | `context_resolver.py` | Genuine missing node; required now |
| `Component_ChangeDetector` | `change_detector.py` | Genuine missing node; required now |
| `Component_KnowledgeSync` | `knowledge_sync.py` | Genuine missing node; required now |
| `Component_AgentCatalog` | `agent_catalog.py` | Real documentation gap; taxonomy work is explicitly deferred |
| `Component_Evaluation` | `evaluation.py` | Real module, but a reusable rubric concept rather than a required O2 component |
| `Component_HealthCheck` | `health_check.py` | Operational checker; defer an operations/tooling component decision |
| `Component_OpencodeCfg` | `opencode_cfg.py` | Naming would expose an implementation file; overlaps runtime config documented by AgentSpecs/Settings |
| `Component_ProjectProfile` | `project_profile.py` | Real Phase-27 concept; taxonomy/context architecture is deferred |
| `Component_Roles` | `roles.py` | Real decoupled concept; do not create module-shaped taxonomy nodes in O2 |
| `Component_RuntimeContext` | `runtime_context.py` | Real Phase-30 subsystem; deserves a later deliberate architecture decision |
| `Component_Skills` | `skills.py` | Real decoupled concept; taxonomy architecture is deferred |
| `Component_WorkflowEngine` | `workflow_engine.py` | Part of one workflow subsystem; separate module node would duplicate `Workflows` |
| `Component_Workflows` | `workflows.py` | Part of one workflow subsystem; later use one cohesive workflow component |

The last ten warnings are safe to ignore **for O2 only**. They are not false in
the narrow sense that the modules lack same-name nodes, but the heuristic
assumes one architecture component per Python file. That granularity is not a
documented Vault rule and would create duplicates or prematurely decide the
deferred taxonomy/workflow architecture.

The heuristic also under-reports documentation gaps: it does not scan core
subpackages (`execution/`, `prompt_library/`, `model_connections/`,
`model_registry/`, `providers/`) or `scripts/web_ui/`, even though the Roadmap
documents the Dashboard, BYOK, prompt, model, and execution subsystems. Thus
making the warning count zero is not equivalent to complete architecture
coverage.

## Documentation drift versus genuinely missing nodes

### Genuine missing nodes

The five Roadmap-required candidates are genuinely absent: no files with those
ids exist, no existing component owns their responsibilities, and both the
Roadmap and Dashboard call them gaps.

### Documentation drift

- `System_Architecture` still labels the Vault bridge as `[P]` and points to
  `scripts/vault_bridge.py`; the implementation is complete at
  `scripts/core/vault_bridge.py`.
- `Doc_API_Integration` also calls the Vault bridge planned.
- `Architecture_Home`, `System_Architecture`, and `Architecture_Overview`
  still index only the original five baseline components.
- The Dashboard hard-codes only the five O2 modules in
  `scripts/generate_dashboard.py::_KNOWN_UNMAPPED_MODULES`, while the live
  Health Check reports fifteen modules. The two surfaces intentionally use
  different scopes today.
- `TASKS.json` still marks `O1` pending although Roadmap Phase 29 says real task
  execution is complete. This is adjacent tracker drift, not part of the
  component-node implementation.

## Nodes that should not be created in O2

- Do not create separate `Component_WorkflowEngine` and
  `Component_Workflows` nodes. They form one workflow definition/execution
  subsystem; a future `Component_Workflows` design should cover both modules
  and `scripts/core/execution/`.
- Do not treat `Component_Orchestrator` as a replacement for that workflow
  subsystem. Vault task orchestration and workflow graph scheduling are
  distinct and both are real.
- Do not create module-per-file nodes for `Roles`, `Skills`, `Evaluation`,
  `AgentCatalog`, `ProjectProfile`, or `RuntimeContext` during O2. Their
  boundaries are part of the explicitly deferred taxonomy architecture.
- Do not create `Component_OpencodeCfg` merely to silence the heuristic. A
  future runtime-configuration/Settings component should describe the actual
  boundary rather than mirror a filename.
- Do not create `Component_HealthCheck` in isolation until the operational
  tooling boundary (`health_check`, `vault_validate`, dashboard generation)
  is designed cohesively.
- Do not recreate retired swarm, self-evolve, archivist, legacy web-app, or
  desktop-GUI components. The root `PLAN.md` is archived and the Roadmap says
  those systems were removed during baseline zero.

## Expected implementation-phase file set

The minimum later implementation should create/modify only:

### New Vault nodes

- `obsidian_vault/01-Architecture/Component_Orchestrator.md`
- `obsidian_vault/01-Architecture/Component_VaultBridge.md`
- `obsidian_vault/01-Architecture/Component_ContextResolver.md`
- `obsidian_vault/01-Architecture/Component_ChangeDetector.md`
- `obsidian_vault/01-Architecture/Component_KnowledgeSync.md`

### Required index/map reconciliation

- `obsidian_vault/01-Architecture/Architecture_Home.md`
- `obsidian_vault/01-Architecture/System_Architecture.md`
- `obsidian_vault/01-Architecture/Architecture_Overview.md`
- `obsidian_vault/05-Documentation/Doc_API_Integration.md`
- `scripts/generate_dashboard.py` (remove the five resolved hard-coded gaps or
  derive them safely)
- `obsidian_vault/Dashboard.md` (regenerate only after the generator changes)
- focused tests in `test/tests/test_generate_dashboard.py`,
  `test/tests/test_knowledge_sync.py`, `test/tests/test_health_check.py`, and
  `test/tests/test_vault_validate.py` as needed for the new links/indexes.

After implementation, `obsidian_vault/Roadmap.md` and `TASKS.json` may mark O2
complete, but only after validation passes. No source/runtime logic should be
changed merely to force all ten deferred heuristic warnings to disappear.

## Acceptance checks for the later implementation

- all five new nodes follow `Node_Schema_Reference` (`type: architecture`,
  `status: active`, `owner: architect`, dates, resolvable `related`, parent);
- `Architecture_Home` lists all five as children;
- every frontmatter/body WikiLink resolves;
- `python scripts/vault_validate.py` remains green;
- KnowledgeSync no longer reports the five Roadmap modules;
- Dashboard no longer lists those five as known gaps;
- the ten deferred module-granularity warnings are documented, not hidden by
  weakening checks or adding fake component nodes.

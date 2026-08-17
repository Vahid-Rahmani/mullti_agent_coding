---
type: task
status: ready
owner: orchestrator
priority: medium
assigned_agent: Agent_Alex
related_component: System_Architecture
dependencies: []
created: 2026-08-15
updated: 2026-08-15
---

# Task_WebUI_Smoke_Test

**Type:** task · **Status:** ready · **Priority:** medium

## Title

Smoke-test the dashboard Tasks → assign → run → result path.

## Description

Exercise the end-to-end task path through the existing Dashboard API without
manual filesystem edits:

1. List tasks via `GET /api/tasks`.
2. Select this task and confirm its detail/result via `GET /api/tasks/Task_WebUI_Smoke_Test`.
3. Confirm assignment and status are persisted through the vault.
4. Confirm a dry-run dispatch stays non-destructive and a real `--yes` run is
   clearly distinguishable.

The task path runs through the existing [[Component_RunHub]] dispatch and the
Orchestrator CLI — do not introduce a second orchestrator or task system.

## Acceptance Criteria

- [ ] task listing, assignment, and status retrieval all round-trip
- [ ] dry-run writes no result and changes no status
- [ ] a real run (with `--yes`) persists status + Agent Report into the node

## Links

- ↑ Parent: [[Tasks_Home]]
- ↔ Assigned Agent: [[Agent_Alex]]
- ↔ Related Component: [[System_Architecture]]
- ↓ Dependencies: *(none)*

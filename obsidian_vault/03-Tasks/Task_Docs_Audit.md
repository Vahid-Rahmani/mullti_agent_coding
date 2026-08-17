---
type: task
status: planned
owner: orchestrator
priority: low
assigned_agent: Agent_Chloe
related_component: System_Architecture
dependencies: [Task_Skill_Evaluation_Extraction]
created: 2026-08-15
updated: 2026-08-15
---

# Task_Docs_Audit

**Type:** task · **Status:** planned · **Priority:** low

## Title

Audit documentation for consistency with the implemented control plane.

## Description

Review `README.md`, `AGENTS.md`, `knowledge/README.md`, and
`obsidian_vault/Roadmap.md` against the actual implementation and reconcile any
drift. This depends on the completed [[Task_Skill_Evaluation_Extraction]] so
the docs cover the Skills and Evaluation abstractions.

## Acceptance Criteria

- [ ] every documented command/flag matches the actual CLI surface
- [ ] task-status vocabulary in the docs matches the orchestrator
- [ ] Roadmap phase checkboxes reflect completed work

## Links

- ↑ Parent: [[Tasks_Home]]
- ↔ Assigned Agent: [[Agent_Chloe]]
- ↔ Related Component: [[System_Architecture]]
- ↓ Dependencies: [[Task_Skill_Evaluation_Extraction]]

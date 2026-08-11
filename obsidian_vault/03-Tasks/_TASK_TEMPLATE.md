---
type: task
status: planned
priority: medium
assigned_agent: Agent_Matthew
related_component: Component_RunHub
dependencies: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Task_<Short_Name>

**Type:** task · **Status:** planned · **Priority:** medium

## Title

<One-line human title>

## Description

<What needs to be done and why. Reference context nodes with [[WikiLinks]] where helpful.>

## Acceptance Criteria

- [ ] criterion 1
- [ ] criterion 2
- [ ] criterion 3

## Links

- ↑ Parent: [[Tasks_Home]]
- ↔ Assigned Agent: [[Agent_Matthew]]
- ↔ Related Component: [[Component_RunHub]]
- ↓ Dependencies: *(none)*

---

## How to use this template

1. Copy this file to `03-Tasks/Task_<Short_Name>.md`.
2. Fill every frontmatter field (the 9 required fields: title, status,
   priority, assigned_agent, related_component, dependencies,
   acceptance_criteria, created, updated).
3. Set `status` per the allowed values: `planned`, `ready`, `in_progress`,
   `blocked`, `completed`, `failed`.
4. `assigned_agent` and `related_component` must be node names that exist
   (they render as `[[WikiLinks]]`).
5. `dependencies` lists other `Task_*` node names that must be `completed`
   first.
6. Add the task to [[Task_Backlog]].
7. Run `python scripts/vault_validate.py` before committing.

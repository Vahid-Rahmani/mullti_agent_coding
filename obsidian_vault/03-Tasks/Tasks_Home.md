---
type: task
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Task_Backlog, System_Architecture, Agents_Home]
---

# Tasks_Home

> Hub for task tracking — the section future Orchestrator agents will read
> from and write to.

**Type:** task · **Status:** active · **Owner:** orchestrator

---

## Purpose

Central index of task nodes. Each task gets its own node with status, priority,
owner, and dependencies.

- ↑ Parent: [[System_Core]]
- ↓ Children:
  - [[Task_Backlog]] — index of all task nodes
  - [[_TASK_TEMPLATE]] — standard task template
  - [[Task_Vault_Health_Check]] — ready
  - [[Task_WebUI_Smoke_Test]] — ready
  - [[Task_Docs_Audit]] — planned
  - [[Task_Skill_Evaluation_Extraction]] — completed
- ↔ Related: [[Decisions_Home]], [[Testing_Home]], [[System_Architecture]], [[Agents_Home]]

## Task Statuses

| Status | Meaning |
|---|---|
| `planned` | Defined, not yet ready to start |
| `ready` | Dependencies met, waiting for pickup |
| `in_progress` | An agent is actively working it |
| `blocked` | Waiting on something outside the task |
| `completed` | Acceptance criteria met |
| `failed` | Attempted but not completed |

## How Agents Read, Update, and Complete Tasks

1. **Read:** the assigned agent opens [[Tasks_Home]] → [[Task_Backlog]] →
   its `Task_*` nodes. It looks for tasks where `status: ready` and its own
   `Agent_*` node is the `assigned_agent`.
2. **Pick up:** before starting, change `status` to `in_progress` and bump
   `updated` to today's date.
3. **Block:** if a dependency or external input is missing, set `status:
   blocked` and record the blocker in the task body.
4. **Complete:** when **all** acceptance criteria are `[x]`, set `status:
   completed` and bump `updated`.
5. **Fail:** if the task cannot be completed, set `status: failed` and record
   the reason in the body.
6. **Rules:**
   - Only the assigned agent (or the orchestrator) transitions a task.
   - Every transition bumps `updated`.
   - A task may only reach `completed` when all acceptance criteria are met.
   - `dependencies` must be `completed` before a task can move `planned → ready`.

## Rules

- Task nodes live in `03-Tasks/` and link up to this hub.
- Every task node follows the [[_TASK_TEMPLATE]].
- Completed tasks are marked `completed` but kept (history is valuable).

## Future Agent Mapping

Reserved for the future **Orchestrator** agent, which reads the backlog here
and tracks progress through task nodes.

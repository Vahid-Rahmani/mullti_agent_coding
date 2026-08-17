---
type: task
status: active
owner: orchestrator
priority: high
assigned_agent: Agents_Home
related_component: System_Architecture
dependencies: []
created: 2026-08-11
updated: 2026-08-11
---

# Task_Backlog

**Type:** task · **Status:** active (index, not a work item) · **Priority:** high

## Purpose

Central index of every task node in `03-Tasks/`. Keep this list in sync with
the task nodes — it is the orchestrator's entry point for planning.

- ↑ Parent: [[Tasks_Home]]
- ↔ Related: [[System_Architecture]], [[Agents_Home]]

## Task Index

| Status | Task | Assigned | Component | Priority |
|---|---|---|---|---|
| `ready` | [[Task_Vault_Health_Check]] | Agent_Sarah | Component_StateTracker | medium |
| `ready` | [[Task_WebUI_Smoke_Test]] | Agent_Alex | System_Architecture | medium |
| `planned` | [[Task_Docs_Audit]] | Agent_Chloe | System_Architecture | low |
| `completed` | [[Task_Skill_Evaluation_Extraction]] | Agent_David | System_Architecture | high |

## Status Legend

| Status | Meaning |
|---|---|
| `planned` | Defined, not yet ready to start |
| `ready` | Dependencies met, waiting for pickup |
| `in_progress` | An agent is actively working it |
| `blocked` | Waiting on something outside the task |
| `completed` | Acceptance criteria met |
| `failed` | Attempted but not completed |

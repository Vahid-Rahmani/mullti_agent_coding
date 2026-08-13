---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agent_Matthew, Agent_Alex, Agent_Sarah, Agent_David, Agent_Elena, Agent_Max, Agent_Chloe, System_Core, System_Architecture]
---

# Agents_Home

> Hub for the agent registry — one node per agent identity. All agents (current
> and future: Architect, Coding, Testing, Orchestrator) get a node here.

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Purpose

Central index of every agent in the control plane: tag and status (model is
runtime-configured per agent in `opencode.json`, not part of identity).

- ↑ Parent: [[System_Core]]
- ↓ Children:
  - [[Agent_Matthew]] — M1
  - [[Agent_Alex]] — M2
  - [[Agent_Sarah]] — M3
  - [[Agent_David]] — M4
  - [[Agent_Elena]] — M5
  - [[Agent_Max]] — M6
  - [[Agent_Chloe]] — M7
- ↔ Related: [[System_Core]], [[System_Architecture]], [[Architecture_Overview]]

## Roster at a Glance

| Tag | Agent | Model |
|---|---|---|
| M1 | `matthew` | runtime-configured (opencode.json) |
| M2 | `alex` | runtime-configured (opencode.json) |
| M3 | `sarah` | runtime-configured (opencode.json) |
| M4 | `david` | runtime-configured (opencode.json) |
| M5 | `elena` | runtime-configured (opencode.json) |
| M6 | `max` | runtime-configured (opencode.json) |
| M7 | `chloe` | runtime-configured (opencode.json) |

> Models are not part of agent identity: any agent can run on any
> user-selected model via the Settings / BYOK layer.

## Integration Status (verified 2026-08-11)

All 7 agents are **fully integrated** with the core components:

- Dispatch: [[Component_RunHub]] (one thread per agent → `opencode run`)
- Definition/identity: [[Component_AgentSpecs]] (specs); model: `opencode.json`
- UI: [[Component_Terminal]] (tabs M1–M7 + MASTER)
- Launchers: [[Component_Launchers]] (inbox workers + launch scripts)
- State: [[Component_StateTracker]] (`state.md` completion records)

### Known gaps (reported, not invented)

- **No task nodes exist yet** — `03-Tasks/` has only the hub, so agent nodes
  link to `[[Tasks_Home]]` rather than individual tasks.
- **MASTER has no node** — the MASTER coordinator has `agent=None` (no opencode
  agent key), so it is not represented as an `Agent_*.md` node by design.
- **Future role agents** (Architect, Coding, Testing, Orchestrator) exist only
  as `[F]` placeholders in the architecture map — no nodes created.

## Rules

- One node per agent identity, named `Agent_<Name>`.
- Update the matching `Agent_*.md` node whenever an agent's **role** changes
  (models are runtime config in `opencode.json`, not identity).
- Future role-based agents (Architect, Coding, Testing, Orchestrator) each get
  their own `Agent_*.md` node linked here.

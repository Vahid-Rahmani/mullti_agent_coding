---
type: task
status: completed
owner: orchestrator
priority: high
assigned_agent: Agent_David
related_component: System_Architecture
dependencies: []
created: 2026-08-14
updated: 2026-08-15
---

# Task_Skill_Evaluation_Extraction

**Type:** task · **Status:** completed · **Priority:** high

## Title

Extract native Skill and Evaluation abstractions (Phase 28).

## Description

Turn useful external-agent knowledge into native, reusable MultiAgentCoding
capabilities without copying external code or adding runtime dependencies.

## Acceptance Criteria

- [x] reusable `Skill` abstraction (schema + registry + provenance)
- [x] reusable `Evaluation` abstraction (criteria + weighted scoring)
- [x] workflow + prompt integration stays backward compatible
- [x] focused tests pass

## Execution Log

- 2026-08-14T18:40:00 — completed

## Agent Report

- actions performed: added scripts/core/skills.py and scripts/core/evaluation.py
- files changed: scripts/core/skills.py; scripts/core/evaluation.py; test/tests/test_skills.py; test/tests/test_evaluation.py
- tests executed: python -m pytest test/tests/test_skills.py test/tests/test_evaluation.py
- test results: pass 58 tests, 0 failures
- remaining issues: none

## Links

- ↑ Parent: [[Tasks_Home]]
- ↔ Assigned Agent: [[Agent_David]]
- ↔ Related Component: [[System_Architecture]]
- ↓ Dependencies: *(none)*

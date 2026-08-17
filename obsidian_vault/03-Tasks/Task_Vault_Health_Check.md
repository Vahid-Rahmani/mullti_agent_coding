---
type: task
status: ready
owner: orchestrator
priority: medium
assigned_agent: Agent_Sarah
related_component: Component_StateTracker
dependencies: []
created: 2026-08-15
updated: 2026-08-15
---

# Task_Vault_Health_Check

**Type:** task · **Status:** ready · **Priority:** medium

## Title

Run the vault and control-plane health checks and report drift.

## Description

Execute the read-only validation and health tooling for the control plane and
report any schema or drift issues. This is an inspection-only task — the
assigned agent must not modify any files:

- `python scripts/vault_validate.py`
- `python scripts/core/health_check.py`
- `python scripts/generate_dashboard.py --check`

## Acceptance Criteria

- [ ] `vault_validate.py` exits 0 (all nodes pass)
- [ ] every health check passes, or is triaged with a concrete reason
- [ ] findings are reported in the Agent Report, never silently fixed

## Links

- ↑ Parent: [[Tasks_Home]]
- ↔ Assigned Agent: [[Agent_Sarah]]
- ↔ Related Component: [[Component_StateTracker]]
- ↓ Dependencies: *(none)*

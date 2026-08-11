---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Doc_Project_Overview, Doc_Architecture, Doc_Agent_Documentation, Doc_Development_Guide, Doc_API_Integration, Doc_Operations, Doc_Troubleshooting, System_Core]
---

# Documentation_Home

> Hub for reference documentation — pointers to repo docs and any vault-side
> reference material.

**Type:** documentation · **Status:** active · **Owner:** all agents

---

## Purpose

Central index of documentation nodes and pointers to key repository documents.

- ↑ Parent: [[System_Core]]
- ↓ Children:
  - [[Doc_Project_Overview]] — Project Overview
  - [[Doc_Architecture]] — Architecture
  - [[Doc_Agent_Documentation]] — Agent Documentation
  - [[Doc_Development_Guide]] — Development Guide
  - [[Doc_API_Integration]] — API/Integration
  - [[Doc_Operations]] — Operations
  - [[Doc_Troubleshooting]] — Troubleshooting
- ↔ Related: [[Architecture_Home]], [[Agents_Home]], [[System_Core]]

## Legend

- **[E] Existing** — the referenced repo document exists today (`status: active`)
- **[G] Generated** — the vault node itself was generated from the audit
- **[P] Planned** — documented as planned; **no content is written** and no
  non-existent functionality is claimed

## Repository Document Map

| Doc | Path | Status | Vault node |
|---|---|---|---|
| README (overview/usage) | `README.md` | [E] | [[Doc_Project_Overview]], [[Doc_Development_Guide]] |
| Agent roster & conventions | `AGENTS.md` | [E] | [[Doc_Agent_Documentation]], [[Doc_Operations]] |
| Archived plan | `PLAN.md` | [E] | [[Doc_Project_Overview]] |
| Repo architecture doc | `docs/architecture/Architecture.md` | [E] | [[Doc_Architecture]] |
| opencode config | `opencode.json` | [E] | [[Doc_API_Integration]] |
| Fallback plugin config | `.opencode/opencode-model-fallback.jsonc` | [E] | [[Doc_API_Integration]] |
| Runtime state | `state.md` | [E] | [[Doc_Operations]] |
| Launchers + workers | `launch_*.bat`, `scripts/run_agent_worker.*` | [E] | [[Doc_Operations]] |
| Test suite | `test/tests/` | [E] | [[Doc_Development_Guide]] |
| Vault bridge + `/vault` command | *(not yet implemented)* | [P] | [[Doc_API_Integration]] |
| Per-role agent usage guide | *(not yet written)* | [P] | [[Doc_Agent_Documentation]] |

## Rules

- Documentation nodes live in `05-Documentation/` and link up to this hub.
- Prefer pointing to canonical repo files over duplicating their content.

## Future Agent Mapping

Read by all agents; written primarily by the future **Architect** and **Orchestrator**.

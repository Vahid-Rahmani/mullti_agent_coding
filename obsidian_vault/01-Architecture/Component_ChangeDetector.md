---
type: architecture
status: active
owner: architect
created: 2026-08-17
updated: 2026-08-17
related: [System_Architecture, Component_KnowledgeSync, Component_VaultBridge, Architecture_Home, Documentation_Home]
---

# Component_ChangeDetector

> Read-only snapshot detection and component-impact mapping.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Compares deterministic snapshots of the repository and Vault to detect and
classify changes, then maps those changes to affected nodes/components without
triggering an agent or modifying user content.

## Source (verified)

- `scripts/core/change_detector.py` — snapshots, diffing, classification,
  deduplication, impact mapping, logging, and CLI commands

## Responsibilities

- Snapshot relevant project and Vault files using timestamps and SHA-256
- Detect created, modified, renamed, and deleted paths
- Classify documentation, architecture, task, agent, source, config, and tests
- Exclude logs, VCS data, virtual environments, and editor/temp artifacts
- Map code changes to linking Vault nodes and Vault changes to components
- Deduplicate repeated detections and append results under `_logs/`

## Dependencies

- Python standard library and read access to the repository/Vault
- Existing WikiLink and `Component_*` naming conventions for impact mapping
- Related to [[Component_KnowledgeSync]] but does not invoke it

## Operational Status

Active as a detection-only CLI (`snapshot`, `detect`, `classify`, `affected`).
No watcher daemon or automatic dispatch is installed.

## Known Limitations

- Rename detection requires identical content hashes
- Impact mapping depends on explicit links and component naming
- Snapshots are point-in-time files, not a continuous filesystem monitor
- Findings are reported; no repair or agent execution is automatic

## Input / Output

- **Input:** current/prior snapshots or a project/Vault-relative path
- **Output:** classified `Change` records, affected node/component names, and
  append-only detection logs

## Related Agents / Tasks / Workflows

- No related execution agent: detection never dispatches any roster agent
- Findings may inform documentation or task planning outside this component

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_KnowledgeSync]], [[Component_VaultBridge]], [[Architecture_Home]], [[Documentation_Home]]

---
type: architecture
status: active
owner: architect
created: 2026-08-17
updated: 2026-08-17
related: [System_Architecture, Component_VaultBridge, Component_ChangeDetector, Architecture_Home, Documentation_Home, Node_Schema_Reference]
---

# Component_KnowledgeSync

> Dry-run-first reconciliation of source implementation and Vault knowledge.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Builds a controlled synchronization plan between the real codebase and the
Vault, reports documentation/code conflicts, and optionally updates only
managed Vault fields or generated marker blocks. Source code is always
read-only.

## Source (verified)

- `scripts/core/knowledge_sync.py` — plans, component mapping, conflict checks,
  managed updates, generated-block handling, logging, and CLI commands

## Responsibilities

- Treat code as implementation truth and Vault nodes as knowledge truth
- Build a non-mutating synchronization plan by default
- Restrict applied changes to managed fields and generated marker sections
- Validate `related_component` references before proposing documentation links
- Report implemented modules without component nodes and documented paths that
  do not exist
- Append structured sync activity to `_logs/sync_log.jsonl`

## Dependencies

- [[Component_VaultBridge]] — schema-aware node reads and safe managed writes
- [[Node_Schema_Reference]] and component naming conventions
- [[Component_ChangeDetector]] is related change intelligence but is not called
  by Knowledge Sync

## Operational Status

Active. `sync` is dry-run by default and requires `--apply` for managed Vault
updates; `check-conflicts` is report-only; `log` reads recent sync history.

## Known Limitations

- Filename-to-Component matching is heuristic and scans top-level core modules
- It does not prove complete architecture coverage of subpackages or the UI
- Human-authored content outside managed/generated regions is never rewritten
- Conflicts are reported, not automatically repaired

## Input / Output

- **Input:** the managed Vault tree and current repository module/file state
- **Output:** `SyncPlan` actions/conflicts, optional managed Vault updates, and
  append-only sync logs

## Related Agents / Tasks / Workflows

- No related execution agent: synchronization never dispatches roster agents
- Its conflict output is consumed by Health Check and operator workflows

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_VaultBridge]], [[Component_ChangeDetector]], [[Architecture_Home]], [[Documentation_Home]], [[Node_Schema_Reference]]

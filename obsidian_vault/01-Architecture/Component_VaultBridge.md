---
type: architecture
status: active
owner: architect
created: 2026-08-17
updated: 2026-08-17
related: [System_Architecture, Component_Orchestrator, Component_ContextResolver, Component_KnowledgeSync, Tasks_Home, Node_Schema_Reference]
---

# Component_VaultBridge

> Safe, schema-aware filesystem boundary for the Obsidian Vault stack.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Owns scoped Vault reads and managed writes so higher layers never rewrite or
execute arbitrary note content. It is the bottom of the Vault-I/O stack and
depends only on the Python standard library.

## Source (verified)

- `scripts/core/vault_bridge.py` — Vault validation, frontmatter parsing,
  relationship resolution, atomic updates, backups, and change logging

## Responsibilities

- Validate Vault/task paths and exclude hubs, indexes, and templates from runs
- Parse node frontmatter strictly and treat Markdown as data only
- Resolve task → agent → component/dependency relationships through WikiLinks
- Restrict writes to managed frontmatter fields while preserving note bodies
- Write atomically with `os.replace` and back up nodes before modification
- Prune old per-node backups and append structured change records
- Refuse invalid, already-running, or terminal task states

## Dependencies

- [[Node_Schema_Reference]] — frontmatter, status, and link contract
- Python standard library only; the bridge does not depend on the Orchestrator

## Operational Status

Active. It is used by the task Orchestrator, Context Resolver, Knowledge Sync,
Dashboard task APIs, and focused Vault integration tests.

## Known Limitations

- Task discovery is intentionally scoped to `03-Tasks/`
- Frontmatter parsing supports the Vault's flat schema, not arbitrary YAML
- Backup retention is bounded per node; it is not a version-control system
- It never opens the Obsidian desktop application or executes note content

## Input / Output

- **Input:** Vault paths, node names, relationship fields, and managed updates
- **Output:** parsed node/task data, resolved paths, atomic node updates,
  backups, and append-only change logs

## Related Agents / Tasks / Workflows

- Agents consume Vault data indirectly through [[Component_Orchestrator]];
  the bridge never dispatches an agent
- [[Tasks_Home]] defines the task nodes managed through this boundary

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_Orchestrator]], [[Component_ContextResolver]], [[Component_KnowledgeSync]], [[Tasks_Home]], [[Node_Schema_Reference]]

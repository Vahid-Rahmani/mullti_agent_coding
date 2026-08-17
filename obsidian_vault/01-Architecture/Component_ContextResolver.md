---
type: architecture
status: active
owner: architect
created: 2026-08-17
updated: 2026-08-17
related: [System_Architecture, Component_Orchestrator, Component_VaultBridge, Tasks_Home, Agents_Home]
---

# Component_ContextResolver

> Deterministic, bounded linked-context resolution for Vault tasks.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Walks outward from one task node through the Vault WikiLink graph and returns
a typed `ContextPackage` for the Orchestrator without loading the whole Vault.

## Source (verified)

- `scripts/core/context_resolver.py` — context data types, bounded traversal,
  cycle/unresolved reporting, snippets, logging, and CLI command

## Responsibilities

- Resolve direct task relationships before deeper graph rings
- Traverse deterministically with configurable depth and node limits
- Keep immediate dependencies and filter deeper nodes by relevant node type
- Skip navigation scaffolding and deeper task nodes from context payloads
- Detect and report cycles and unresolved links without looping
- Log a structured resolution record to `_logs/context_log.jsonl`

## Dependencies

- [[Component_VaultBridge]] — validated Vault access, task resolution, node
  reads, link parsing, and shared logging/time primitives

## Operational Status

Active. The Orchestrator uses it for task dispatch, and the CLI exposes bounded
context inspection. Defaults are depth 2 and at most 10 included nodes.

## Known Limitations

- Context is link-based; unlinked repository knowledge is not discovered
- Node snippets are bounded and do not provide full-document retrieval
- Cycles are reported but not repaired

## Input / Output

- **Input:** Vault root, task path, maximum depth, and maximum node count
- **Output:** deterministic `ContextPackage` with typed nodes, unresolved
  references, cycles, and traversal limits

## Related Agents / Tasks / Workflows

- The dynamically assigned agent under [[Agents_Home]] receives the rendered
  context through [[Component_Orchestrator]]
- Root task metadata comes from nodes indexed by [[Tasks_Home]]

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_Orchestrator]], [[Component_VaultBridge]], [[Tasks_Home]], [[Agents_Home]]

---
type: system
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Linking_Standard, Node_Hierarchy, Vault_Map]
---

# System_Core

> **Root node** of the MultiAgentCoding knowledge graph. Every section of the
> vault hangs off this node. Start here to navigate the system.

**Type:** system · **Status:** active · **Owner:** all agents

---

## Purpose

The central index for the control plane's Obsidian knowledge graph. Links to
the main sections below and to the two standards documents that govern how the
graph is written and maintained.

## Main Sections

- ↑ (root — no parent)
- ↓ [[Architecture_Home]] — system architecture & component knowledge
  - ↳ [[System_Architecture]] — high-level architecture map
- ↓ [[Agents_Home]] — agent registry & identities
- ↓ [[Tasks_Home]] — task tracking
- ↓ [[Decisions_Home]] — decision records (ADRs)
- ↓ [[Documentation_Home]] — reference documentation
- ↓ [[Testing_Home]] — test plans, results, and QA knowledge
- ↔ [[Linking_Standard]] — how `[[WikiLinks]]` are written (read first)
- ↔ [[Node_Hierarchy]] — parent/child rules & orphan prevention
- ↔ [[Node_Schema_Reference]] — the node frontmatter schema & validation rules

## Vault Layout

```
obsidian_vault/
├── 00-System/      ← System_Core, Linking_Standard, Node_Hierarchy, Vault_Map
├── 01-Architecture/
├── 02-Agents/
├── 03-Tasks/
├── 04-Decisions/
├── 05-Documentation/
└── 06-Testing/
```

See [[Vault_Map]] for the full graph.

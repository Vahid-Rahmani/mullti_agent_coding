---
type: system
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Linking_Standard, System_Core]
---

# Node_Hierarchy

> Rules for parent/child relationships between nodes. These keep the graph a
> clean tree with a single canonical root — easy for humans, easy for agents.

**Type:** system · **Status:** active · **Owner:** all agents

---

- ↑ Parent: [[System_Core]]
- ↔ Related: [[Linking_Standard]], [[Node_Schema_Reference]]

## Level Model

| Level | Role | Examples |
|---|---|---|
| 0 | **Root** — exactly one | `System_Core` |
| 1 | **Section hubs** — one per numbered folder | `Architecture_Home`, `Agents_Home`, … |
| 2+ | **Content nodes** — belong to exactly one section | `Architecture_Overview`, `Agent_Matthew`, … |

## Rules

1. **One root.** `System_Core` is the only level-0 node. Nothing links *up* from it.
2. **Exactly one canonical parent.** Every node (except the root) has exactly
   one parent — its section hub. The parent link is written as `↑ Parent:`.
3. **Tree, not a free graph.** The canonical structure is a tree. Cross-links
   (`↔ Related:`) may exist between any nodes but are never the parent link.
4. **Hubs are level 1.** Each numbered folder (`00`–`06`) has exactly one hub
   node; the hub is the only child of `System_Core` for that folder.
5. **Content lives at level 2+.** New knowledge notes go inside a numbered
   folder and link up to that folder's hub.
6. **Hub anatomy** — every hub must contain:
   - title + one-line purpose
   - `↑ Parent: [[System_Core]]` (or the relevant hub)
   - `↓ Children:` bulleted `[[…]]` list of its content nodes
   - `↔ Related:` optional cross-links

## Orphan Prevention

A node is an **orphan** if nothing links to it. Prevent orphans by:

1. Creating a node **inside its section folder** and immediately adding the
   `↑ Parent:` link to the hub.
2. Adding the child to the hub's `↓ Children:` list in the same change.
3. Running the link-validation check (see `Vault_Map`) after any batch of
   edits — it reports nodes with no inbound links.
4. Never deleting a hub while it still has children.

## Section → Future Agent Mapping

| Section | Primary consumer |
|---|---|
| 00-System | Orchestrator (standards, root) |
| 01-Architecture | Architect |
| 02-Agents | All (registry of identity) |
| 03-Tasks | Orchestrator |
| 04-Decisions | All |
| 05-Documentation | All |
| 06-Testing | Testing |

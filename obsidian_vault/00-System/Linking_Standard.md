---
type: system
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Node_Hierarchy, System_Core]
---

# Linking_Standard

> The one and only rule set for writing `[[WikiLinks]]` inside this vault.
> Both humans and AI agents must follow this exactly.

**Type:** system · **Status:** active · **Owner:** all agents

---

- ↑ Parent: [[System_Core]]
- ↔ Related: [[Node_Hierarchy]], [[Node_Schema_Reference]]

## 1. Node Name = Filename

Every Markdown file in the vault is a **node**. Its node name is the filename
without the `.md` extension.

- File `System_Core.md` → node `System_Core`
- File `Agent_Matthew.md` → node `Agent_Matthew`

## 2. Naming Convention — Snake_Case

All new nodes use `Snake_Case`: words separated by single underscores, no
spaces, no hyphens, no special characters.

| ✅ Correct | ❌ Incorrect |
|---|---|
| `[[System_Core]]` | `[[System Core]]` |
| `[[Agent_Matthew]]` | `[[agent-matthew]]` |
| `[[Architecture_Overview]]` | `[[Architecture Overview]]` |

## 3. Unique Names Vault-Wide

Node names must be **unique across the entire vault**. Duplicate filenames are
forbidden — they make `[[Node_Name]]` ambiguous. If a name is taken, disambiguate
with a more specific name (e.g. `Test_Plan_Login` instead of `Test_Plan`).

## 4. Display Aliases

When the raw name is awkward in prose, use an alias:

- `[[Agent_Matthew|Matthew]]`
- `[[System_Core|System Core]]`

The link target stays canonical; the alias only changes the visible text.

## 5. Link Placement

- A **parent** links to each of its **children** at least once.
- Every **child** links **up** to its parent (Obsidian's backlinks panel then
  reinforces the tree automatically).
- Links live in a labeled block: `↑ Parent:`, `↓ Children:`, `↔ Related:`.

## 6. Cross-Links

Cross-links between nodes in different sections are **encouraged** (they power
the graph view), but they are *additional* relationships. They never replace
the single canonical parent link.

## 7. Legacy Files

Pre-existing files keep their current names:

- `Dashboard.md` → `[[Dashboard]]`
- `Roadmap.md` → `[[Roadmap]]`

New content may link to them with those exact names.

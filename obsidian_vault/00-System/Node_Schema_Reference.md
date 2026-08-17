---
type: system
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Linking_Standard, Node_Hierarchy]
---

# Node_Schema_Reference

> The canonical schema for every node in this vault. Both humans and AI agents
> must follow this document. The validator (`scripts/vault_validate.py`)
> enforces it automatically.

**Type:** system · **Status:** active · **Owner:** all agents

---

## 1. Frontmatter (required on every node)

Every node file must open with a YAML frontmatter block:

```yaml
---
type: <node_type>
status: <status_value>
owner: <owner>
created: YYYY-MM-DD
updated: YYYY-MM-DD
related: [Node_A, Node_B]   # optional
---
```

### Fields

| Field | Required | Values |
|---|---|---|
| `type` | ✅ | `system`, `architecture`, `agent`, `task`, `decision`, `documentation`, `test` |
| `status` | ✅ | depends on type (see §2) |
| `owner` | ✅ | agent key or role: `matthew`…`chloe`, `architect`, `orchestrator`, `testing`, `all` |
| `created` | ✅ | ISO date `YYYY-MM-DD` (node creation date) |
| `updated` | ✅ | ISO date `YYYY-MM-DD` (last edit date — bump on every change) |
| `related` | ⭕ | comma-separated list of node names that must resolve to real files |

## 2. Node Types & Allowed Status Values

| Type | Section folder | Allowed status values | Primary owner |
|---|---|---|---|
| `system` | `00-System/` | `active`, `draft` | `orchestrator`, `all` |
| `architecture` | `01-Architecture/` | `active`, `draft`, `superseded` | `architect` |
| `agent` | `02-Agents/` | `active`, `retired` | `orchestrator` |
| `task` | `03-Tasks/` | `active`, `draft`, `planned`, `ready`, `in_progress`, `blocked`, `completed`, `failed` | `orchestrator` |
| `decision` | `04-Decisions/` | `active`, `draft`, `proposed`, `accepted`, `superseded` | `architect` |
| `documentation` | `05-Documentation/` | `active`, `draft` | `all` |
| `test` | `06-Testing/` | `active`, `draft`, `passed`, `failed`, `blocked` | `testing` |

**Enforcement:** a node's `type` must match its section folder (e.g. a node in
`02-Agents/` must have `type: agent`).

**Task status vocabulary:** hub/index nodes (`Tasks_Home`, `Task_Backlog`) use
`active`/`draft`; leaf task nodes use the Orchestrator's execution vocabulary —
`planned` → `ready` → `in_progress` → `completed` | `blocked` | `failed`. This
is the same set `scripts/core/vault_bridge.py` and the Orchestrator's
`TRANSITIONS` enforce, so any task that can be dispatched also validates.
Optional task frontmatter: `priority`, `assigned_agent`, `related_component`,
`dependencies`, and a temporary `role` override (written by the Dashboard,
never to `roles.json`).

## 3. Node References (WikiLinks)

- References use `[[Node_Name]]` exactly per [[Linking_Standard]]: snake_case,
  unique vault-wide, alias `[[Node|Display]]` allowed.
- **Parent link** — every node except the root `System_Core` must contain
  `↑ Parent: [[...]]` in its body.
- **Child links** — hubs list their children as `↓ Children:`.
- **Cross-links** — optional, either as `↔ Related:` body links or as
  frontmatter `related:` entries (validator resolves both).
- Frontmatter `related` values must exist as node names.

## 4. Parent / Child Rules

Per [[Node_Hierarchy]]:

1. One root: `System_Core` (level 0).
2. Exactly one canonical parent per node — its section hub (level 1).
3. Content nodes live at level 2+ inside their section folder.
4. Hub anatomy: title + purpose, `↑ Parent`, `↓ Children`, `↔ Related`.
5. No duplicate node names vault-wide.

## 5. Orphan Prevention

- A node is an orphan when nothing links to it.
- When creating a node: add its `↑ Parent` link **and** add it to the hub's
  `↓ Children` list in the same change.
- The validator (`scripts/vault_validate.py`) reports all nodes with zero
  inbound links and exits non-zero if any exist.

## 6. Validation

Run from the repo root:

```bash
python scripts/vault_validate.py
```

Checks performed (all must pass):

- frontmatter exists and is parseable
- required fields present (`type`, `status`, `owner`, `created`, `updated`)
- `type` valid and matches section folder
- `status` allowed for the node's type
- dates are `YYYY-MM-DD`
- `related` entries resolve to real files
- no duplicate node names
- every non-root node has an `↑ Parent:` link
- no orphan nodes

Exit code `0` = all good; `1` = one or more violations (listed on stdout).

## 7. Example (agent node)

```markdown
---
type: agent
status: active
owner: orchestrator
created: 2026-08-11
updated: 2026-08-11
related: [Agents_Home, Agent_Alex]
---

# Agent_Matthew

**Type:** agent · **Status:** active · **Owner:** orchestrator

---

## Identity
...
```

---

- ↑ Parent: [[System_Core]]
- ↔ Related: [[Linking_Standard]], [[Node_Hierarchy]], [[Vault_Map]]

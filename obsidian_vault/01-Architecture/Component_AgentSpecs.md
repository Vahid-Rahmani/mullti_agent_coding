---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-11
related: [System_Architecture, Component_RunHub, Component_Terminal, Agents_Home]
---

# Component_AgentSpecs

> Agent definition layer — the single source of truth for the agent roster.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Defines every control-plane agent (M1–M7) plus the MASTER coordinator as plain
`AgentSpec` instances (**identity only** — tag/name/agent key). The registry
derives the roster and tab order. Runtime models are resolved from
`opencode.json` (not from a spec), and a CLI verifies the roster's
mode/fallback invariants against `opencode.json`.

## Source (verified)

- `scripts/core/agents/base.py` — `AgentSpec` dataclass
- `scripts/core/agents/{matthew,alex,sarah,david,elena,max,chloe,master}.py`
- `scripts/core/agents/registry.py` — `AGENTS`, `TABS`, lookups
- `scripts/core/agents/__main__.py` — CLI: `list`, `roster`, `model`, `verify`
- `scripts/core/agents/constants.py` — `PROJECT_ROOT`, status values

## Responsibilities

- Declare the 7 plain agents + MASTER (identity only)
- Provide roster/tab order to [[Component_Terminal]] and [[Component_RunHub]]
- Resolve runtime models for launcher workers (`python -m scripts.core.agents model <a>`)
- Verify roster invariants against `opencode.json` (`python -m scripts.core.agents verify`)

## Dependencies

- `opencode.json` (runtime config; drift-checked, not parsed by launchers)
- Standard library only (dataclasses, pathlib)

## Input / Output

- **Input:** agent tag/key queries from terminal, hub, and launchers
- **Output:** `AgentSpec` objects, roster tuples, runtime model strings

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_RunHub]], [[Component_Terminal]], [[Agents_Home]]

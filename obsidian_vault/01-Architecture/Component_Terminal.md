---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-11
related: [System_Architecture, Component_RunHub, Component_AgentSpecs]
---

# Component_Terminal

> ZOVA — the full-screen retro terminal UI for the control plane.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Primary human interface. Provides tabbed agent workspace (M1–M7 + MASTER),
scrollable per-tab consoles, model status bar, loading/progress bar, and a
rounded prompt box. Dispatches typed tasks to the agent of the active tab (or
all agents on MASTER).

## Source (verified)

- Entry point: `scripts/terminal_app.py` (thin shim re-exporting core + ui)
- UI app: `scripts/ui/terminal_app.py` (`RetroTerminalApp`)
- Rendering: `scripts/ui/rendering.py`, `scripts/ui/palette.py`, `scripts/ui/theme.py`

## Responsibilities

- Render the dashboard, consoles, loading bar, and prompt box (prompt_toolkit).
- Route input: slash commands (`/tab /help /cd /status /clear /stop /theme /quit`)
  vs. plain tasks (dispatched via [[Component_RunHub]]).
- Track per-tab state, scroll, abort (Esc/Ctrl+G), and theme switching.

## Dependencies

- [[Component_RunHub]] — task dispatch + telemetry
- [[Component_AgentSpecs]] — roster (`AGENTS`, `TABS`) for tabs and model bar
- prompt_toolkit (Python package)

## Input / Output

- **Input:** user keystrokes and commands; hub events (`seq`-streamed)
- **Output:** rendered UI; dispatch calls into `HUB.run(...)`

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_RunHub]], [[Component_AgentSpecs]], [[Agents_Home]]

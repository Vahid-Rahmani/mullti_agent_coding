---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Documentation_Home, Doc_Operations, Doc_Troubleshooting, Component_Terminal, Component_Launchers]
---

# Doc_Development_Guide

**Type:** documentation · **Status:** active (existing — pointer card) · **Owner:** all

## Category

Development Guide

## Purpose

Short guide for developing/extending the control plane. Details live in the
repo `README.md` (existing); this card summarizes the workflow without
duplicating the full text.

## Quick Workflow (verified)

1. Launch the terminal: `launch_terminal.bat` or
   `python scripts/terminal_app.py`.
2. Or launch the 7-window launcher: `launch_agents.bat`.
3. Type a task on an agent tab (M1–M7) or MASTER (all agents).
4. Tasks are dispatched via `opencode run --agent <a> --auto -m <m> "<prompt>"`.

## Testing

- Test suite: `python -m unittest discover -s test/tests` (201 tests, unittest).
- Smoke checks: `launch_agents.bat --smoke`, `python scripts/terminal_app.py --smoke`.

## Repository References

| Doc | Path | Status |
|---|---|---|
| README (setup/usage) | `README.md` | existing |

## Links

- ↑ Parent: [[Documentation_Home]]
- ↔ Related: [[Doc_Operations]], [[Doc_Troubleshooting]], [[Testing_Home]]

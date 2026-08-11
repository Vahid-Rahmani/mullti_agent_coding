---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Documentation_Home, Component_Launchers, Component_StateTracker, Doc_Troubleshooting]
---

# Doc_Operations

**Type:** documentation · **Status:** active (existing — pointer card) · **Owner:** all

## Category

Operations

## Purpose

Operational knowledge: launching, inbox flow, state, and runtime knobs.
Details live in `README.md` and `AGENTS.md` (existing); this card summarizes
the verified facts.

## Verified Operations

- **Launch 7-window launcher:** `launch_agents.bat` (builds roster from
  `python -m scripts.core.agents roster`).
- **Launch terminal:** `launch_terminal.bat` or `python scripts/terminal_app.py`.
- **Inbox flow:** drop a task into `_inbox/<agent>.task` → worker runs it →
  output appended to `_logs/<agent>.log` → task moved to `_inbox/done/`.
- **State:** [[Component_StateTracker]] writes `state.md` (atomic writes).
- **TLS bypass (opt-in):** `ZOVA_ALLOW_INSECURE_TLS=1` →
  `NODE_TLS_REJECT_UNAUTHORIZED=0` for self-signed/intercepting certs.

## Repository References

| Doc | Path | Status |
|---|---|---|
| README (operations) | `README.md` | existing |
| AGENTS.md (execution env) | `AGENTS.md` | existing |

## Links

- ↑ Parent: [[Documentation_Home]]
- ↔ Related: [[Component_Launchers]], [[Doc_Troubleshooting]]

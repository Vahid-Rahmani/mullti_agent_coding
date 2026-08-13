---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Documentation_Home, System_Architecture, Doc_Architecture]
---

# Doc_Project_Overview

**Type:** documentation · **Status:** active (existing — pointer card) · **Owner:** all

## Category

Project Overview

## Purpose

One-page orientation to the MultiAgentCoding control plane: what it is, how
the pieces fit, and where the canonical docs live. Full text is **not**
duplicated here — see the repo files.

## Repository References

| Doc | Path | Status |
|---|---|---|
| Project README | `README.md` | existing |
| Archived master plan | `PLAN.md` | existing (archived 2026-08-11) |
| Architecture map (vault) | [[System_Architecture]] | generated |

## Highlights (verified)

- 7 plain agents (M1–M7) + MASTER, identity only — model and role are
  runtime concerns (opencode.json / roles.json).
- Two entry points: ZOVA retro terminal (`launch_terminal.bat`) and the
  7-window inbox launcher (`launch_agents.bat`).
- Dispatch: `opencode run --agent <a> --auto -m <model> "<prompt>"`.

## Links

- ↑ Parent: [[Documentation_Home]]
- ↔ Related: [[System_Architecture]], [[Doc_Architecture]], [[Agents_Home]]

# Dashboard — MultiAgentCoding

> **Control plane for a self-evolving multi-agent coding system.**
> 7 specialized agents · Swarm protocol · Retro terminal UI · Obsidian-powered docs

---

## Quick Links

| Page | Description |
|------|-------------|
| [[Roadmap]] | High-level project roadmap with checklist phases |
| [[prompts/]] | Individual prompt tracking notes |
| [[agents_logs/]] | Per-agent work logs and run records |

---

## Project at a Glance

- **Phase:** Running — `feature/ui-loading-refactor`
- **Active agents:** system-architect, analyst, planner, backend-dev, frontend-dev, tester, reviewer
- **Models:** All free-tier (`deepseek-v4-flash-free`, `big-pickle`, `ling-3.0-tiny-free`)
- **UI:** ZOVA retro terminal (`python scripts/terminal_app.py`)
- **Swarm:** ON by default (stale-peer detection + helper takeover)

---

## Key Files (Repo Root)

| File | Purpose |
|------|---------|
| `PLAN.md` | Detailed implementation plan & architecture decisions |
| `TASKS.json` | Structured task tracking (dependencies, owners, status) |
| `AGENTS.md` | Agent roles, workflow, conventions, fallback policy |
| `opencode.json` | Agent definitions, model assignments, provider config |
| `state.md` | Runtime state (phase, last run, completion log, restart log) |

---

## Agent Roster

| Tag | Agent | Role | Model |
|-----|-------|------|-------|
| M1 | `system-architect` | Architecture + design approval (read-only) | `deepseek-v4-flash-free` |
| M2 | `analyst` | Requirements analysis (read-only) | `big-pickle` |
| M3 | `planner` | PLAN.md + TASKS.json (read-only) | `big-pickle` |
| M4 | `backend-dev` | Backend implementation | `deepseek-v4-flash-free` |
| M5 | `frontend-dev` | Frontend implementation | `deepseek-v4-flash-free` |
| M6 | `tester` | Test authoring + execution | `big-pickle` |
| M7 | `reviewer` | Code review + approve/reject (read-only) | `ling-3.0-tiny-free` |

---

## Slash Commands (ZOVA Terminal)

`/tab` `/help` `/cd` `/model` `/mode` `/agents` `/status` `/clear` `/stop` `/swarm` `/proposals` `/evolve` `/quit`

---

*Open this vault in [Obsidian](https://obsidian.md) for graph view, backlinks, and wiki-link navigation.*

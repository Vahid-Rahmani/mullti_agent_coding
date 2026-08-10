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
- **Active agents:** system-architect, analyst, planner, backend-dev, frontend-dev, tester, reviewer (M7: immutable audit)
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
| M7 | `reviewer` | Obsidian-Vault-Sync & Final Audit (immutable) | `ling-3.0-tiny-free` |

---

## Slash Commands (ZOVA Terminal)

`/tab` `/help` `/cd` `/model` `/mode` `/agents` `/agents-log` `/status` `/clear` `/stop` `/swarm` `/proposals` `/evolve` `/audit` `/quit`

---

## Recent Activity (Dataview)

```dataview
TABLE file.ctime as "Created", target_agent as "Agent", status as "Status"
FROM "prompts"
SORT file.ctime DESC
LIMIT 10
```

```dataview
TABLE agent_role as "Role", last_updated as "Last Active", status as "Status"
FROM "agents_logs"
WHERE agent_tag
SORT last_updated DESC
```

---

## Vault Structure

```
obsidian_vault/
├── Dashboard.md          ← you are here
├── Roadmap.md            ← phased project plan
├── prompts/              ← auto-generated prompt logs
│   ├── _TEMPLATE.md
│   └── prompt-NNN.md
└── agents_logs/          ← per-agent run logs
    ├── _TEMPLATE.md
    └── M{N}_{Role}.md
```

---

*Open this vault in [Obsidian](https://obsidian.md) for graph view, backlinks, and wiki-link navigation. Enable the Dataview plugin for live query tables.*

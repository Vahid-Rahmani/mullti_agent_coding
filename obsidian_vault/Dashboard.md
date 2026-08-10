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
- **Active agents:** matthew, alex, sarah, david, elena, max, chloe (M7: immutable documentation audit)
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
| M1 | `matthew` | Matthew — architecture + master coordination (read-only) | `deepseek-v4-flash-free` |
| M2 | `alex` | Alex — backend, APIs, Python logic, and data handling | `deepseek-v4-flash-free` |
| M3 | `sarah` | Sarah — TUI, frontend, UX, and rendering | `deepseek-v4-flash-free` |
| M4 | `david` | David — QA, TDD, tests, and debugging | `big-pickle` |
| M5 | `elena` | Elena — code quality and security audit (read-only) | `ling-3.0-tiny-free` |
| M6 | `max` | Max — DevOps, automation, and environment stability | `deepseek-v4-flash-free` |
| M7 | `chloe` | Chloe — documentation and Obsidian knowledge audit (immutable) | `ling-3.0-tiny-free` |

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

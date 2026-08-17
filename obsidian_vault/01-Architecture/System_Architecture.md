---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-17
related: [Architecture_Overview, Agents_Home, Component_Terminal, Component_RunHub, Component_AgentSpecs, Component_StateTracker, Component_Launchers, Component_Orchestrator, Component_VaultBridge, Component_ContextResolver, Component_ChangeDetector, Component_KnowledgeSync]
---

# System_Architecture

> The high-level architecture map of the MultiAgentCoding control plane.
> Components below reflect **real files verified in the project** — nothing
> invented.

**Type:** architecture · **Status:** active · **Owner:** architect

---

## Legend

- `[E]` **Existing** — component exists in the codebase today
- `[P]` **Planned** — designed but not yet implemented
- `[F]` **Future** — reserved, not yet designed in detail

## System Map

```mermaid
flowchart TD
    PROJ["multi_agent_coding (control plane)"]
    CORE["Core System"]
    TERM["[E] Component_Terminal"]
    HUB["[E] Component_RunHub"]
    SPECS["[E] Component_AgentSpecs"]
    STATE["[E] Component_StateTracker"]
    LAUNCH["[E] Component_Launchers"]
    ORCH["[E] Component_Orchestrator"]
    BRIDGE["[E] Component_VaultBridge"]
    CONTEXT["[E] Component_ContextResolver"]
    CHANGES["[E] Component_ChangeDetector"]
    SYNC["[E] Component_KnowledgeSync"]
    AGENTS["Agents (M1-M7)"]
    TASKS["03-Tasks"]
    TESTS["06-Testing"]
    DOCS["05-Documentation"]

    PROJ --> CORE
    CORE --> TERM
    CORE --> HUB
    CORE --> SPECS
    CORE --> STATE
    CORE --> LAUNCH
    CORE --> ORCH
    CORE --> BRIDGE
    CORE --> CONTEXT
    CORE --> CHANGES
    CORE --> SYNC
    CORE --> AGENTS
    CORE --> TASKS
    CORE --> TESTS
    CORE --> DOCS
```

## Component Index

| Status | Component | Source (verified) | Responsibility |
|---|---|---|---|
| [E] | [[Component_Terminal]] | `scripts/terminal_app.py` → `scripts/ui/` | Full-screen prompt_toolkit UI (ZOVA retro terminal, tabs M1–M7 + MASTER) |
| [E] | [[Component_RunHub]] | `scripts/core/run_hub.py` | Thread-safe dispatch engine: one thread per agent → `opencode run` |
| [E] | [[Component_AgentSpecs]] | `scripts/core/agents/` | Agent definitions (`AgentSpec`) + registry + `__main__.py` CLI |
| [E] | [[Component_StateTracker]] | `scripts/core/state_tracker.py` | Atomic read/write of `state.md` session checkpoint |
| [E] | [[Component_Launchers]] | `launch_agents.bat`, `launch_terminal.bat`, `scripts/run_agent_worker.ps1/.sh` | 7-window inbox launcher, terminal launcher, inbox-polling workers |
| [E] | [[Component_Orchestrator]] | `scripts/core/orchestrator.py` | Controlled Vault task lifecycle, dispatch, locking, and result persistence |
| [E] | [[Component_VaultBridge]] | `scripts/core/vault_bridge.py` | Safe scoped Vault I/O, atomic updates, backups, and relationship resolution |
| [E] | [[Component_ContextResolver]] | `scripts/core/context_resolver.py` | Deterministic bounded linked-context packages for tasks |
| [E] | [[Component_ChangeDetector]] | `scripts/core/change_detector.py` | Detection-only snapshots, classification, and impact mapping |
| [E] | [[Component_KnowledgeSync]] | `scripts/core/knowledge_sync.py` | Dry-run-first documentation/code reconciliation and conflict reporting |

## Agents

The roster is documented under [[Agents_Home]] with one node per agent
([[Agent_Matthew]] … [[Agent_Chloe]]). Agents dispatch through
[[Component_RunHub]] using their runtime models resolved from `opencode.json`
(the Settings / BYOK layer) — identity never pins a model.

## Planned / Future

- `[P]` `/vault` terminal command — planned ZOVA terminal command to open the
  vault / notes via the Obsidian URI scheme.
- `[F]` Role-based agents (Architect, Coding, Testing, Orchestrator) — future;
  the vault sections (01–06) are pre-structured for them.

## Links

- ↑ Parent: [[Architecture_Home]]
- ↔ Related: [[Architecture_Overview]], [[Agents_Home]], [[Tasks_Home]], [[Testing_Home]], [[Documentation_Home]]

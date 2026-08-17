---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-17
related: [Architecture_Overview, System_Architecture]
---

# Architecture_Home

> Hub for system architecture knowledge — the section future Architect agents
> will read from and write to.

**Type:** architecture · **Status:** active · **Owner:** architect

---

## Purpose

Central index for architecture nodes: system maps, component designs, data
models, and integration contracts.

- ↑ Parent: [[System_Core]]
- ↓ Children:
  - [[System_Architecture]] — high-level architecture map (components, agents, sections)
  - [[Architecture_Overview]] — current baseline-zero system overview
  - [[Component_Terminal]] — ZOVA retro terminal UI
  - [[Component_RunHub]] — thread-safe dispatch engine
  - [[Component_AgentSpecs]] — agent definition layer + registry
  - [[Component_StateTracker]] — state.md persistence
  - [[Component_Launchers]] — launchers + inbox workers
  - [[Component_Orchestrator]] — controlled Vault task execution
  - [[Component_VaultBridge]] — safe schema-aware Vault I/O
  - [[Component_ContextResolver]] — bounded linked task context
  - [[Component_ChangeDetector]] — detection-only snapshot and impact mapping
  - [[Component_KnowledgeSync]] — docs/code reconciliation and drift reporting
- ↔ Taxonomy architecture: `docs/architecture/repository-driven-agent-taxonomy.md`
- ↔ Related: [[Documentation_Home]], [[Decisions_Home]]

## Rules

- Architecture content nodes live in `01-Architecture/` and link up to this hub.
- Each architecture decision should also create a node under [[Decisions_Home]].

## Future Agent Mapping

Reserved for the future **Architect** agent. When that agent is created, it
reads/writes nodes in this section.

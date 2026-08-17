# Repository-Driven Agent Taxonomy

**Status:** implemented through Phases A–H (2026-08-17).

The taxonomy is the control plane's documented relationship layer:

```text
Repository evidence + internal/original capability records
  → capabilities + declared role relations
  → generated taxonomy.json
  ⊕ curated overrides.json
  → effective taxonomy + agent coverage matrix
  → runtime context, Agent Catalog, Taxonomy API, and Web UI
```

`knowledge/taxonomy/skills.json`, `relations.json`, and
`internal_capabilities.json` are structured source inputs. `taxonomy.json` is
regenerated deterministically; `overrides.json` contains durable curated
choices only. Legacy `agent_context.json` is read for compatibility and can be
migrated into overrides during a controlled rebuild without deleting the user
file.

Integrity checks verify that the artifact is current with its sources, curated
references resolve, the effective result remains coherent, and every registered
runtime agent has coverage. Runtime dispatch never rebuilds the taxonomy.

See [the implementation design](repository-driven-agent-taxonomy-design.md) for
the detailed data model and [the forensic audit](agent-taxonomy-forensic-audit.md)
for the original findings.

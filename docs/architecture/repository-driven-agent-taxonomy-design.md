# Repository-Driven, Capability-Driven Agent Taxonomy — Design

**Status.** DESIGN ONLY. No source code, `roles.json`, `agent_catalog.py`,
`runtime_context.py`, `skills.py`, `prompt_library`, or frontend files are
modified by this document. It defines the architecture that will **replace**
the current hard-coded taxonomy.

**Companion document.** This design is the corrective follow-up to
`docs/architecture/agent-taxonomy-forensic-audit.md`. It answers the same
question the audit could only diagnose: *how do we make the taxonomy emerge
from repository capabilities instead of being typed by hand?* Every section
below names the audit finding it closes (e.g. "closes 5.1").

**The one-sentence design.** Introduce a first-class `Capability` entity that
is **derived from structured repository evidence**, make `Capability` the join
key between Repository → Role → Skill → Prompt Profile → Agent, split the data
into a **regenerable `taxonomy.json`** and a **curated `overrides.json`**, and
re-point the runtime/UI/catalog at the **effective** view
(`taxonomy ⊕ overrides`) so nothing downstream needs a hand-maintained
`ROLE_SKILL_MAP`, `ROLE_CATEGORY_MAP`, or `AGENT_PRESETS` literal.

---

# 1. Design Goals

1. **Emerge, don't enumerate.** Categories, capabilities, and the
   role/skill/prompt edges must be **computed from repository evidence**, not
   asserted as Python/data literals. Adding a reference repository must be able
   to change the taxonomy without editing `roles.json` or `agent_catalog.py`.
   *(closes audit §5.1–5.3, §3.)*

2. **`Capability` is the join key.** The missing entity in the audit
   (Finding 5.3) becomes first-class: a stable id with evidence, domain,
   provenance, and reverse edges to roles/skills/profiles/agents. "Capability"
   stops being a free-form string tuple on three unrelated objects.

3. **Regenerable vs curated, strictly separated.** Everything that can be
   re-derived from evidence lives in a regenerable file; everything a human
   pinned lives in an overlay file that a rebuild never touches.
   *(closes audit §8, §12, §16.4, §18 "overrides silently clobbered".)*

4. **All seven agents are covered, always.** The derived matrix must assign
   every roster agent (derived from `scripts/core/agents/registry.py`, not a
   hard-coded set) at least one role + its derived skills/profiles. Coverage is
   a **computed invariant**, not a side effect of hand-picking keys.
   *(closes audit §6.1–6.3, §16.1.)*

5. **Runtime identity/model decoupling is preserved.** `AgentSpec`
   (tag/name/key only) and `opencode.json` (model/mode/fallback) stay exactly
   where they are. The taxonomy composes **onto** them; it never redefines them.
   *(keeps audit §10.)*

6. **Backward compatible.** `runtime_context.build_runtime_prompt()` keeps its
   signature and its composition order; `run_hub`/`orchestrator`/`planner`
   keep calling it. The unconfigured-agent raw-prompt fallback is preserved.

7. **Deterministic and testable.** The build pipeline and every resolver are
   pure functions of their inputs (no timestamps, no hash order, no network at
   resolve time). Rebuild twice → byte-identical output.

8. **Curated intent survives.** The deliberate, hand-authored *content*
   (role expertise text, skill procedure steps, prompt text, and human-chosen
   agent↔capability bindings) is kept — it just moves to the curated layer
   instead of masquerading as a derived taxonomy.

---

# 2. Architectural Principles

| # | Principle | Rationale |
|---|---|---|
| P1 | **Evidence before entity.** No capability, category, role, skill, or prompt profile is added without a linked evidence record. | Closes the audit's core gap: today `sources` is a decorative string. |
| P2 | **Content is curated; structure is derived.** The *prose* (role responsibilities, skill steps, prompt text) is human-authored and never regenerated. The *graph* (which capability belongs to which role/agent/category) is derived. | Keeps the good curated material from audit §10 while making the taxonomy real. |
| P3 | **One source per edge.** Every relationship (role→skill, role→category, role→prompt, agent→role) has exactly one producing computation. | Kills the `ROLE_SKILL_MAP` ↔ `AGENT_PRESETS` duplication (audit §7.4). |
| P4 | **Derived layer is disposable.** `taxonomy.json` may be deleted and rebuilt from evidence at any time with no information loss. | This is the definition of "regenerable". |
| P5 | **Overrides are additive patches, not copies.** `overrides.json` stores only deltas (rename/merge/reassign/reorder), never full re-statements of the derived layer. | Prevents drift between the derived and curated copies of the same fact. |
| P6 | **Identity/model are out of scope.** Capabilities/roles/skills/profiles never reference a model, provider, or agent key. | Preserves the decoupling in `AGENTS.md`; the matrix binds agents, nothing else does. |
| P7 | **Read-only resolution at runtime.** Dispatch resolves the effective view; it never mutates taxonomy files. Only the build and the Settings API mutate. | Keeps `run_hub`/`orchestrator`/`planner` side-effect-free. |
| P8 | **Vocabulary coherence.** One canonical id namespace for roles, capabilities, skills, and profiles; the prompt `role` string becomes a reference into it (or is dropped). | Closes the two-vocabulary bridge problem (audit §7.2). |

---

# 3. Capability Entity

## Why it exists

The forensic audit (Finding 5.3) found that "capability" exists only as a
free-form `tuple[str, ...]` on `PromptProfile.capabilities`,
`Skill.capabilities`, and `TaskProfile.capabilities` — with no shared
vocabulary, no id, and no source link. That is precisely why role→skill
resolution was forced into a hand-maintained `ROLE_SKILL_MAP`. A first-class
`Capability` gives the graph a join node.

## Definition

```text
Capability {
  id            : str          # stable slug, e.g. "source-management"
  name          : str          # human label, e.g. "Source Management"
  description   : str          # one-to-two sentence definition
  domains       : [str]        # category membership signals (see §7)
  evidence      : [evidence_id]# → §4, the records that support it
  source_repos  : [repo_id]    # → which repositories support it
  origin        : original | adapted | source-derived
  license       : str          # aggregated provenance (most-restrictive wins)
}
```

`id` is the canonical reference used everywhere else. Nothing references a
capability by name.

## The questions it must answer

| Question | Field |
|---|---|
| What capability is this? | `id`, `name`, `description` |
| Which repositories support it? | `source_repos` |
| Which evidence supports it? | `evidence` |
| Which category/domain? | `domains` (clustered into categories, §7) |
| Which roles use it? | reverse index `capability → roles` built from `Role.capabilities` |
| Which skills implement it? | reverse index `capability → skills` built from `Skill.capabilities` |
| Which prompt profiles depend on it? | reverse index `capability → profiles` built from `PromptProfile.capabilities` |
| Which agents should receive it? | `AgentCapabilityMatrix` (§11) |

## Provenance

Every non-`original` capability carries `source_repos` + `license` + `origin`
exactly as `Skill`/`PromptProfile` already do today (audit §10 keeps that
discipline). A capability supported by `strix` (Apache-2.0) and `open-notebook`
(MIT) records both repos and the most-restrictive license for any downstream
attribution.

## Source of truth / generated vs curated

- **Derived** (in `taxonomy.json`): the capability records themselves, produced
  by the build step from repository evidence (§4). Their `name`/`description`
  are initially seeded from the existing skill/prompt `capabilities` literals
  (§16 migration) and from evidence `supports` entries.
- **Curated** (in `overrides.json`): human edits to a capability's
  `name`/`description`/`domains`, or a human-asserted capability that has no
  machine evidence yet (`origin: curated`).

## Impact on existing code

- New module `scripts/core/taxonomy/capabilities.py` (registry + reverse
  indexes + `capabilities_for_role`/`capabilities_for_skill`/…).
- `skills.py` `Skill.capabilities` and `prompt_library` profile `capabilities`
  stop being free strings and become references into the capability registry
  (validated at load). The `Skill`/`PromptProfile` schemas themselves are kept.
- `ROLE_SKILL_MAP` and `suggest_prompts_for_role` are replaced by capability
  overlap (§13).

---

# 4. Repository Evidence Model

## Why it exists

The audit's Findings 5.1/5.2: nothing reads `knowledge/sources/*.md`, and the
"reference map" in `knowledge/sources/README.md` is documentation that can
drift. The system needs a **machine-parseable** statement of what each
repository demonstrates, so a rebuild can recompute capabilities.

## Model

```text
Repository → Evidence → Capability
```

- **Repository** — identity + licensing + extraction mode:
  ```text
  Repository { id, url, license, source_type, extraction_mode, code_reuse }
  ```
- **Evidence** — one claim/pattern per record, tied to capabilities:
  ```text
  Evidence {
    id            : str          # "<repo>:<slug>", e.g. "open-notebook:citation-discipline"
    repository    : repo_id
    kind          : pattern | workflow | output-policy | methodology | architecture
    summary       : str          # the extracted claim, in our own words
    supports      : [capability_id]   # capabilities this evidence demonstrates
    confidence    : direct | inferred
    requires_inspection : bool    # true ⇒ capability map is provisional
  }
  ```

## Storage — machine block in the existing source files

Keep the human prose in `knowledge/sources/<source>.md` (audit §10 keeps them),
and add a **YAML frontmatter block** the build step consumes (frontmatter is
already a project convention in the Obsidian vault). Example:

```yaml
---
id: open-notebook
license: MIT
extraction_mode: ideas
domains: [research, knowledge-management]
evidence:
  - id: citation-discipline
    kind: pattern
    summary: "Separate a source's claim from the AI's interpretation."
    supports: [source-management, citation, provenance]
    confidence: direct
    requires_inspection: false
  - id: source-as-first-class
    kind: architecture
    summary: "Keep sources as reusable first-class assets."
    supports: [source-management, knowledge-organization]
    confidence: direct
    requires_inspection: false
---
# lfnovo/open-notebook
… (existing human prose unchanged) …
```

## Why frontmatter (not a second JSON file)

- One file per source stays one file (no drift between "the record" and "the
  machine input").
- The prose remains readable by humans; the frontmatter is the build input.
- `requires_inspection: true` lets the build ship a capability marked
  **provisional** instead of silently inventing support (see §19).

## Source of truth / generated vs curated

- The frontmatter (evidence) is **curated** — a human asserts what a repository
  demonstrates and maps it to capability ids.
- The capabilities **derived** from that evidence are **generated** into
  `taxonomy.json`.

This split is the key insight: *the derivation is automated; the evidence
judgment is human.* The pipeline cannot invent a capability with no evidence,
and it cannot lose one that has evidence.

## Impact on existing code

- New `scripts/core/taxonomy/evidence.py` (parse frontmatter → `Repository` +
  `Evidence` records + validation).
- `knowledge/sources/*.md` gain frontmatter (one-time migration, §16 step 2).
- `knowledge/sources/README.md` "reference map" table becomes **generated**
  output (or is replaced by a link to the generated map) so it can no longer
  drift.

---

# 5. Taxonomy Model

## Why it exists

The audit §8 proposed a single persistent, regenerable store layered over the
existing registries. This section makes it concrete.

## Files

```text
knowledge/taxonomy/taxonomy.json     ← DERIVED source of truth (regenerable)
knowledge/taxonomy/overrides.json    ← CURATED source of truth (never regenerated)
knowledge/taxonomy/effective.json    ← derived cache: taxonomy ⊕ overrides
                                       (build artifact; optional, see below)
```

## `taxonomy.json` (derived)

```json
{
  "schema_version": 1,
  "generated_from": "knowledge/sources/*.md (frontmatter evidence)",
  "repositories":   [ { "id": "open-notebook", "url": "...", "license": "MIT", ... } ],
  "evidence":       [ { "id": "open-notebook:citation-discipline", ... } ],
  "capabilities":   [ { "id": "source-management", "name": "Source Management", ... } ],
  "categories":     [ { "id": "research", "name": "Research", "capabilities": [ ... ] } ],
  "role_edges":     { "researcher":        { "capabilities": [ ... ], "category": "research" } },
  "skill_edges":    { "structured-research": { "capabilities": [ ... ] } },
  "prompt_edges":   { "research-source-manager": { "capabilities": [ ... ] } },
  "role_skill_edges":   { "researcher": [ "structured-research", "source-verification" ] },
  "role_prompt_edges":  { "researcher": [ "research-source-manager" ] },
  "agent_assignments":  { "sarah": { "capability_ids": [ ... ], "role_ids": [ ... ],
                                      "skill_ids": [ ... ], "prompt_profile_ids": [ ... ] } },
  "coverage": { "uncovered_agents": [], "uncovered_capabilities": [] }
}
```

Notes:
- `role_edges`/`skill_edges`/`prompt_edges` hold only the **capability links**;
  the role/skill/profile *content* stays in `roles.json`, `skills.json`, and
  the prompt library (see §6). The taxonomy references them by id.
- `role_skill_edges` and `role_prompt_edges` are **computed** by capability
  overlap (§8, §9, §10) — this is what replaces `ROLE_SKILL_MAP`.
- `agent_assignments` is the **derived** capability matrix (§11).
- `coverage` is the computed drift report the UI surfaces.

## `overrides.json` (curated)

```json
{
  "schema_version": 1,
  "category_overrides":       { "rename": {"content":"content-seo"}, "merge": {"docs":"documentation"} },
  "capability_overrides":     { "source-management": { "name": "...", "domains": [ "research" ] } },
  "role_overrides":           { "researcher": { "capabilities": [ "source-management", "citation" ],
                                                "category": "research" } },
  "skill_order_overrides":    { "researcher": [ "structured-research", "source-verification" ] },
  "agent_assignment_overrides": { "sarah": { "capability_ids": [ "source-management" ] } },
  "curated_presets":          [ { "id": "empty", ... } ]
}
```

## Effective view

```text
effective = derived ⊕ overrides
```

Resolution order for every lookup: start from `taxonomy.json`, apply
`overrides.json` deltas, produce the effective entity. The effective view is
**never hand-edited**; it is a pure function. Runtime, catalog, and UI consume
only the effective view.

## Source of truth / generated vs curated

| Fact | Generated (`taxonomy.json`) | Curated (`overrides.json`) |
|---|---|---|
| Repository identity/license | ✓ (from frontmatter) | — |
| Evidence records | ✓ | — |
| Capability records | ✓ (from evidence `supports`) | name/description/domain tweaks |
| Categories | ✓ (clustered, §7) | renames/merges |
| Role→capability, Role→category | ✓ (from role `capabilities`) | explicit pins |
| Role→skill, Role→prompt | ✓ (capability overlap) | explicit order pins |
| Agent→capability/role | ✓ (coverage + fallback) | explicit bindings |
| Presets | ✓ (resolved from matrix) | curated combos (e.g. Empty Agent) |

## Impact on existing code

- New `scripts/core/taxonomy/build.py` (produces `taxonomy.json`),
  `overrides.py` (load/merge), `effective.py` (resolver).
- `agent_catalog.py` and `runtime_context.py` re-point at the effective view
  (§12, §13); their literal constants are removed only after the parity gate
  (§16 step 5).
- No change to `AgentSpec`, `opencode.json`, or the model registry.

---

# 6. Generated vs Override Data

## The split, stated once

- **Generated** = anything the build can re-derive from repository evidence +
  existing curated content's `capabilities` fields. Regenerable, byte-stable,
  deletable.
- **Override** = a human's delta over the generated result. Survives rebuild,
  and always **wins** over the generated value for the same key.

## Explicit field-by-field contract

| Entity / field | Generated | Override | Notes |
|---|---|---|---|
| `Capability.id` | ✓ (sluggified from first evidence) | rename (id maps) | id rename is an override map, not a regeneration |
| `Capability.name/description` | seeded, regenerable | ✓ | human polish survives |
| `Capability.domains` | ✓ (from evidence + repo `domains`) | ✓ | override pins domain membership |
| `Capability.evidence/source_repos/license` | ✓ | — | provenance is derived, never hand-copied |
| `Category` set | ✓ (clustering) | rename/merge/split | overrides mutate membership |
| `Role` content (text) | — | — | **curated, lives in `roles.json`** (not regenerated) |
| `Role.capabilities` | seeded from current data | ✓ | the curated link the build validates |
| `Role → Skill` edge | ✓ (overlap) | order/extra pin | replaces `ROLE_SKILL_MAP` |
| `Role → Prompt` edge | ✓ (overlap) | order/extra pin | replaces `suggest_prompts_for_role` |
| `Skill`/`PromptProfile` content | — | — | **curated** (skills move to `skills.json` data) |
| `Skill.capabilities` | — (validated) | ✓ | curated link, validated against vocabulary |
| `Agent → Capability` | ✓ (coverage fallback) | ✓ | the curated binding is the primary input |
| `Agent → Role/Skill/Prompt` | ✓ (derived from capabilities) | ✓ | override wins |
| `Presets` | ✓ (resolved) | ✓ (curated combos) | Empty Agent is curated |

## Why roles are content-curated but edge-derived

Role *expertise* (responsibilities/tools/rules) is judgment that no repository
parser should invent — it is authored once. But *which capabilities* a role
covers and *which category* it belongs to are exactly what should re-derive
when evidence changes. This is the precise answer to the brief's "do not require
manually rewriting roles when a repository changes": the role text is stable;
the role's capability graph regenerates.

## Merge rules (deterministic)

1. Start with `taxonomy.json`.
2. Apply `category_overrides` (rename → merge → split).
3. Apply `capability_overrides`, `role_overrides`, `skill_order_overrides`.
4. Apply `agent_assignment_overrides`.
5. Recompute downstream edges affected by steps 2–4.
6. `curated_presets` are appended to (never regenerate-replaced) resolved
   presets, deduped by id.

If an override references an id that no longer exists in the derived layer,
the build **fails loudly** (a drift error) rather than silently dropping it —
this makes "orphaned override" detectable by a test.

---

# 7. Category Derivation

## Why it exists

The audit §3 shows 8 hand-written `AgentCategory` entries plus 14
`ROLE_CATEGORY_MAP` rows. The brief forbids assuming that fixed list. Categories
must be a **derived clustering** of capabilities.

## Derivation rule

1. Collect every capability's `domains` (from evidence + repository `domains`).
2. Normalize domain labels (lowercase, hyphenate, dedupe).
3. **Cluster** capabilities whose `domains` intersect (connected components of
   the capability↔domain bipartite graph). Each cluster becomes a `Category`
   whose `id` is the cluster's most-frequent domain label (or a slug from the
   joined capabilities if tied).
4. A category's `name` is a human-readable label derived from its id (or
   supplied by `category_overrides.rename`).

## Properties

- **Emergent, not enumerated.** Adding `open-seo`-derived capabilities grows a
  `content`/`seo` cluster; removing them lets the cluster shrink or vanish. The
  build never consults a fixed list.
- **A capability may belong to multiple categories** via multiple domains
  (e.g. a "fix-verify-loop" capability sits in both a `security` and a
  `verification` cluster). Categories are many-to-many with capabilities.
- **Human control is an override, not an assumption.** If the clustering is
  noisy, `category_overrides.rename/merge/split` pins the result; the override
  survives rebuild.

## Source of truth / generated vs curated

- **Generated**: the cluster set and membership.
- **Curated**: renames/merges/splits and display names.

## Impact on existing code

- Removes `AGENT_CATEGORIES` and `ROLE_CATEGORY_MAP` literals
  (`agent_catalog.py`).
- `GET /api/settings/role-categories` and the catalog sidebar consume the
  derived categories (§14) with an unchanged response shape.

---

# 8. Role Derivation

## Why it exists

The audit §7.1/7.3: roles carry no `capabilities`/`category`/`source`, so their
taxonomy half is divorced into `ROLE_CATEGORY_MAP` + `ROLE_SOURCES` +
`ROLE_SKILL_MAP`. Role derivation restores the relationship structurally.

## Model

```text
Role (content, curated in roles.json)
  + capabilities : [capability_id]   # NEW — the join into the taxonomy
  + source / license / origin        # NEW — provenance, like skills/profiles
```

## What is derived from a role

| Edge | Derivation |
|---|---|
| Role → Category | union of `capability.domains` → cluster (§7) |
| Role → Skill | `Role.capabilities ∩ Skill.capabilities`, ordered deterministically (§9) |
| Role → Prompt Profile | `Role.capabilities ∩ PromptProfile.capabilities` (+ role reference, §10) |
| Role → Agent | reverse of `Agent → Capability` matrix (§11) |

## Reusability (kept)

Roles stay **reusable** and **many-to-many** (audit §10 keeps the mechanism in
`roles.py`):

- a role may contain multiple capabilities;
- a capability may belong to multiple roles;
- a role may be assigned to multiple agents, and an agent holds many roles.

The existing `roles.py` dataclass and `assignments` map are extended with a
`capabilities` field (and provenance), not replaced. `roles_for_agent`,
`assign_roles`, `render_role_context` keep their behavior; only the input
records gain fields.

## Source of truth / generated vs curated

- Role **content** and its `capabilities` list are **curated** (in `roles.json`).
- Role→category, role→skill, role→prompt, role→agent edges are **generated**
  (in `taxonomy.json`), overridable in `overrides.json`.

## Impact on existing code

- `roles.py` `Role` gains `capabilities`, `source`, `license`, `origin`
  (backward-compatible defaults).
- `ROLE_CATEGORY_MAP`, `ROLE_SOURCES`, and `ROLE_SKILL_MAP` literals are
  deleted after parity (§16).
- `prompt_library.suggest_prompts_for_role` and `registry._KEYWORDS` bridge is
  replaced by capability-overlap (§10, §13).

---

# 9. Skill Relationship

## Why it exists

The brief: `Capability → Skill`. Skills are *implementations* (operating
procedures) of capabilities. Today `Skill.capabilities` exists but is a free
string tuple; `ROLE_SKILL_MAP` is the only role→skill knowledge and it is
hand-maintained.

## Model

```text
Capability → Skill      (Skill.capabilities references capability ids)
Role → Skill            (Role.capabilities ∩ Skill.capabilities)
```

## No capability metadata duplication

A skill does **not** restate a capability's `name`/`description`/`evidence`/
`domains`. It references `capability_id`s only. The capability record owns that
metadata; the skill owns its `steps` and its own provenance. This is the
answer to "do not duplicate capability metadata inside every skill."

## Role→Skill resolution (replaces `ROLE_SKILL_MAP`)

```
role_skills(role) =
  skills S where S.capabilities ∩ Role.capabilities ≠ ∅,
  ordered by:
    1. the number of shared capabilities (desc), then
    2. the role's declared capability order (stable), then
    3. skill id (lexicographic tie-break),
  with `skill_order_overrides[role]` taking precedence when present.
```

This is deterministic and, after the migration parity step (§16 step 4),
reproduces today's `ROLE_SKILL_MAP` output exactly — then continues to work
when a new skill/capability is added (no map to update).

## Source of truth / generated vs curated

- Skill content + its `capabilities` list: **curated** (moved from
  `BUILTIN_SKILL_DICTS` into a `skills.json` data file; the `Skill` schema and
  `validate_skill` stay).
- Role→skill edges: **generated**, with order overrides.

## Impact on existing code

- `skills.py` loses `BUILTIN_SKILL_DICTS`/`SKILL_CATEGORIES` literals (moved to
  data); keeps `Skill`, `validate_skill`, `render_skill_context`,
  `suggest_skills_for_task` (task classifier, unchanged).
- `runtime_context.skills_for_roles` delegates to the taxonomy resolver instead
  of reading `ROLE_SKILL_MAP`.

---

# 10. Prompt Profile Relationship

## Why it exists

The brief: `Capability / Role → Prompt Profile`. Prompt profiles are the
"how to think" text and must stay reusable, and **must not** become the
taxonomy source of truth.

## Model

```text
Capability → PromptProfile     (Profile.capabilities references capability ids)
Role → PromptProfile           (Role.capabilities ∩ Profile.capabilities)
```

## The two-vocabulary problem is removed

Today `PromptProfile.role` is a string like `software_engineer` while
`roles.json` ids are `python-developer` — bridged by fragile keyword matching
(audit §7.2). In the new model:

- `PromptProfile.role` becomes an **optional role id reference** (or is dropped
  in favor of `capabilities`).
- Role→profile resolution uses capability overlap, not keywords:
  ```
  role_profiles(role) =
    profiles P where P.capabilities ∩ Role.capabilities ≠ ∅ OR P.role == role.id,
    ordered deterministically as in §9.
  ```

## Prompt profiles are not the taxonomy

Profiles keep their `source`/`license`/`origin` provenance and are **content**
(curated). The taxonomy references them by id and computes the role→profile
edges; it never generates prompt text and never stores profile content.

## Source of truth / generated vs curated

- Profile content + `capabilities`: **curated** (prompt library unchanged in
  schema).
- Role→profile edges: **generated** (overridable).

## Impact on existing code

- `prompt_library/schema.py` `PROMPT_ROLES`/`CATEGORIES` and
  `registry._KEYWORDS` are consolidated into the canonical capability/role
  vocabulary (one-time, §16 step 7).
- `runtime_context.prompt_profiles_for_roles` delegates to the resolver instead
  of `suggest_prompts_for_role`.

---

# 11. Agent Capability Matrix

## Why it exists

The audit §6: only `matthew` and `alex` have roles; presets never reach the
terminal/orchestrator paths; and the "all agents covered" test encodes the
hard-coding by fiat. The matrix is the derived artifact that assigns
capabilities to **all** agents.

## Model

```text
Agent → multiple capabilities
      → multiple roles         (roles whose capabilities overlap the agent's)
      → multiple skills        (skills whose capabilities overlap)
      → multiple prompt profiles
```

```json
"agent_assignments": {
  "sarah": {
    "capability_ids":     [ "source-management", "citation", "provenance" ],
    "role_ids":           [ "researcher" ],
    "skill_ids":          [ "structured-research", "source-verification" ],
    "prompt_profile_ids": [ "research-source-manager" ]
  }
}
```

## Primary binding: Agent → Capability

The **primary, human-meaningful** assignment is `agent → capability_ids` (not
`agent → roles`). This is the smallest curated fact. Everything else derives:

1. `agent.role_ids` = roles whose `capabilities` ⊆/∩ `agent.capability_ids`
   (with `agent_assignment_overrides.role_ids` able to pin/add).
2. `agent.skill_ids` = §9 resolution over those roles' capabilities.
3. `agent.prompt_profile_ids` = §10 resolution.

## Coverage policy (so all seven are covered without hard-coding them)

1. The roster is read from `agents/registry.py` (the dynamic set, not a typed
   list).
2. **Every capability** must be covered by ≥1 agent; **every agent** must be
   covered by ≥1 capability (and thus ≥1 role).
3. The primary bindings come from `overrides.json`
   `agent_assignment_overrides` (seeded at migration from today's
   `roles.json` assignments + presets, §16 step 6).
4. Any uncovered agent or uncovered capability is filled by a **deterministic
   fallback** (capability → least-loaded agent whose existing capabilities are
   in the same domain cluster; tie-break by agent key), and reported in
   `coverage` so the operator can replace the fallback with an explicit
   override.
5. `coverage.uncovered_agents`/`uncovered_capabilities` are empty **only when**
   the matrix is complete — this is what the §18 all-agent test asserts.

## Runtime identity/model preserved

`AgentSpec` (tag/name/key) and `opencode.json` (model/mode/fallback) are
untouched. The matrix adds *capabilities/roles/skills/profiles* on top of the
identity; it never assigns a model or redefines the roster.

## Source of truth / generated vs curated

- `agent → capability_ids`: **curated primary**, with generated fallback.
- `agent → roles/skills/profiles`: **generated** (from capabilities), overridable.

## Impact on existing code

- New `scripts/core/taxonomy/coverage.py` (matrix + fallback + coverage report).
- `roles.json` assignments are superseded by the matrix (kept as a migration
  seed; see §16), or remain as a read-through for the `roles_for_agent`
  compatibility shim.
- `runtime_context.role_derived_*_ids_for_agent` reads the matrix.

---

# 12. Agent Catalog Redesign

## Why it exists

The audit §6.2/§11: `agent_catalog.py` is a designer-only template island of
hand-written `AGENT_PRESETS` + `ROLE_CATEGORY_MAP` + `ROLE_SOURCES`, and its
"coverage" is a side effect of typing all 7 keys. The catalog must become a
**resolver over the taxonomy**, not the taxonomy itself.

## New layering

```text
Taxonomy (effective view)
        ↓
Agent capability composition (matrix, §11)
        ↓
Catalog / presets  (resolved views + curated combos)
```

## Preset = resolved binding, not a hand-typed row

A preset is a **named view** of the effective matrix for one agent (or a
curated override combo):

```text
Preset {
  id            : str          # "researcher", "empty", ...
  agent_key     : str          # which runtime agent
  role_ids      : [..]         # from matrix
  skill_ids     : [..]         # from matrix (role-derived)
  prompt_profile_ids : [..]    # from matrix
  capabilities  : [..]         # from matrix (shown as badges)
  category      : str          # derived category (§7)
  model / mode  : ""           # still a runtime concern (opencode.json)
  provenance    : { source_repos, license }   # surfaced, not hidden
}
```

- **Derived presets** are generated deterministically for every agent in the
  matrix (one preset per agent's primary role, or per role if an agent holds
  several).
- **Curated presets** (e.g. the **Empty Agent**, or a deliberate multi-skill
  combo) live in `overrides.json.curated_presets` and are appended after the
  derived set (dedup by id). The Empty Agent stays first and zero-config.

## What disappears

- `AGENT_CATEGORIES`, `AGENT_PRESETS`, `ROLE_CATEGORY_MAP`, `ROLE_SOURCES`
  literals are removed (after parity, §16).
- The `sources=("usestrix/strix", …)` citation tuples become real
  `capability.evidence`/`source_repos` references surfaced per preset.

## Catalog API shape is stable

`GET /api/agent-catalog` keeps returning `{categories: […], presets: […]}` with
the same `AgentPreset.to_dict()` shape — only the data source changes to the
effective taxonomy. This keeps `workspace.js` addNode-from-preset working.

## Preset application becomes persistent

Selecting "apply preset to agent" writes the binding into
`agent_assignment_overrides` (and through the existing
`PUT /api/settings/agents/{agent}/roles|skills|prompts`), so the agent's
terminal/orchestrator runtime actually receives it — closing audit §6.2.

## Source of truth / generated vs curated

- Derived presets: **generated**.
- Curated combos + Empty Agent: **curated** (`overrides.json`).

## Impact on existing code

- `agent_catalog.py` becomes a resolver: `list_categories()`,
  `list_presets()`, `get_preset()`, `resolve_preset_config()`,
  `build_preset_runtime_prompt()`, `validate_catalog()` keep their signatures
  and now read the effective taxonomy. `validate_catalog()` becomes a
  **taxonomy-integrity check** (capabilities resolve, categories derived, all
  agents covered).

---

# 13. Runtime Integration

## Why it exists

The brief: the runtime must not require a hand-maintained `ROLE_SKILL_MAP`, and
should preserve the desirable composition precedence.

## Consumers

| Module | Today | After |
|---|---|---|
| `runtime_context.py` | `build_runtime_prompt` + `ROLE_SKILL_MAP` + `prompt_profiles_for_roles` | same builder, re-pointed at the effective taxonomy |
| `run_hub.py` | calls `build_runtime_prompt(agent, user_request=…)` | unchanged |
| `orchestrator.py` | calls `build_runtime_prompt` + task-level `role` override | unchanged (role override maps to a capability/role override at resolve time) |
| `execution/planner.py` | per-node `roles`/`skills`/`instruction` | unchanged |

## Precedence, mapped onto capabilities

Current (audit §10): explicit > agent assignment > role-derived > suggestion.
New equivalent:

```text
1. explicit runtime args          (skill_ids/prompt_profile_ids/role_ids on the call)
2. curated override               (overrides.json agent_assignment_overrides)
3. capability-derived             (matrix §11 → §9/§10 overlap)   [was "role-derived"]
4. task-based suggestion          (suggest_skills_for_task / prompt classifiers)
```

`runtime_context._resolve_skills` / `_resolve_profiles` keep their
`explicit arg > agent assignment > derived` shape; the "agent assignment" now
reads the effective matrix and the "derived" step is capability overlap, so
`ROLE_SKILL_MAP` and `suggest_prompts_for_role` disappear.

## Composition order (preserved)

`build_runtime_prompt` keeps its fixed order — identity → roles → skills →
profile/instruction → project → workflow → task → user request — and its
raw-request fallback for an unconfigured agent. No signature change.

## Provenance rendering

`render_skill_context` / `render_prompt_profile_context` additionally surface
the **capability ids** and **source repos** for each resolved item, consistent
with today's `source`/`license` output.

## Source of truth / generated vs curated

The runtime reads the **effective view** (taxonomy ⊕ overrides) read-only, per
P7. It never triggers a build.

## Impact on existing code

- `runtime_context.py`: delete `ROLE_SKILL_MAP` + `_validate_role_skill_map`;
  `skills_for_roles`/`prompt_profiles_for_roles` delegate to
  `taxonomy.effective`.
- `run_hub.py`, `orchestrator.py`, `planner.py`: no changes required.

---

# 14. UI Integration

## Why it exists

The UI must consume the derived taxonomy and must **not** contain another
hard-coded copy (audit §14).

## Settings

- **Roles/Skills/Prompts pickers** (`settings.js`) group by the derived
  categories (§7) and show each assignment's **derived vs overridden** state
  (so a user knows what a rebuild will or won't touch).
- The role picker shows each role's **capability badges** + provenance
  (source repo + license), sourced from `GET /api/taxonomy`.
- Applying a preset writes an override (persists), not just a designer node.

## Workspace

- **Catalog sidebar** (`workspace.js`) renders the derived categories/presets
  (§12) with capability + provenance badges per card.
- `addNodeFromPreset` is unchanged in behavior (still materializes a
  `WorkflowNode`); the preset now carries derived data.

## New "Taxonomy" view

- Lists `Repository → Evidence → Capability → Role/Skill/Prompt` with rebuild
  status, drift warnings (source frontmatter changed since last build), and the
  coverage report (§11) — including any agent/capability filled by the
  deterministic fallback.

## API backing (unchanged shapes)

- `GET /api/agent-catalog`, `GET /api/settings/role-categories`,
  `GET /api/prompts` keep shapes; data source changes.
- New: `GET /api/taxonomy`, `GET /api/taxonomy/coverage`,
  `POST /api/taxonomy/rebuild` (operator-gated).

## Source of truth / generated vs curated

UI reads the effective view (never the raw generated file), so overrides are
always reflected.

## Impact on existing code

- `settings.js`, `workspace.js`, `app.js`, `index.html`: consume derived data +
  derived/override flags; no hard-coded taxonomy literals in JS.
- `routes.py` / `settings.py`: add `/api/taxonomy*` endpoints; re-point
  existing handlers at the effective view.

---

# 15. Repository Refresh Pipeline

## Why it exists

The brief requires a deterministic, testable refresh mechanism.

## Pipeline (pure, staged)

```text
1. refresh sources        (re-read knowledge/sources/*.md frontmatter; optional git pull)
        ↓
2. validate evidence      (schema, license, supports → known/derivable capability ids)
        ↓
3. build taxonomy.json    (deterministic; §5)
        ↓
4. apply overrides.json   (merge; §6)
        ↓
5. compute agent matrix   (§11) + coverage report
        ↓
6. persist effective view (effective.json cache) + coverage report
        ↓
7. refresh UI/runtime     (invalidate in-memory cache; UI re-fetches)
```

## Determinism guarantees

- Steps 2–6 are pure functions of (source frontmatter, `roles.json`,
  `skills.json`, prompt profiles, `overrides.json`). No timestamps, no hash
  ordering, no network in the build.
- Build output is written atomically (temp + `os.replace`, matching
  `roles.py`/`runtime_context.save_*` conventions).
- The build **never writes** `overrides.json` (P4/P5); it only reads it.

## Drift detection

- Each build records a `content_hash` of the evidence frontmatter. A
  `check`/`status` command (mirroring `knowledge_sync`) reports "dirty" when
  sources changed but no rebuild ran, and "orphaned override" when an override
  references a now-missing id.
- Rebuild is **operator-gated** via `POST /api/taxonomy/rebuild` or a CLI
  (`python -m scripts.core.taxonomy build`); dispatch never rebuilds.

## Source of truth / generated vs curated

- `taxonomy.json` + `effective.json` cache: generated, disposable.
- `overrides.json`: curated, durable.

## Impact on existing code

- New `scripts/core/taxonomy/__main__.py` (build/check/status).
- `routes.py` gated rebuild endpoint; `knowledge_sync.py` drift check extended
  to cover taxonomy sources.

---

# 16. Existing Data Migration

## Why it exists

The brief: migrate `roles.json`, `agent_catalog.py`, `skills.py`,
`prompt_library`, and existing agent assignments **without destroying user
configuration**.

## Principle

Migrate by **deriving** today's literals into the new files, then **verify
parity** before deleting anything. Nothing is destroyed until the new pipeline
reproduces the old behavior exactly.

## Steps

1. **Freeze.** Snapshot the current literals as the parity fixture
   (`ROLE_SKILL_MAP`, `AGENT_PRESETS`, `ROLE_CATEGORY_MAP`, `ROLE_SOURCES`,
   `BUILTIN_SKILL_DICTS`, prompt profiles, `roles.json`).
2. **Machine-fy sources.** Add YAML frontmatter evidence blocks to the 7
   `knowledge/sources/*.md` (from the existing "Useful concepts /
   patterns / integration target" prose, §19).
3. **Extract the capability vocabulary.** Build `Capability` records from the
   union of `Skill.capabilities`, profile `capabilities`, and the new evidence
   `supports` — assigning ids and linking evidence (dedupe by slug).
4. **Generate the first `taxonomy.json`** and verify **parity**: the derived
   `role_skill_edges` must equal today's `ROLE_SKILL_MAP`, and derived
   categories must equal today's `AGENT_CATEGORIES` + `ROLE_CATEGORY_MAP`
   (the audit's §17.3 parity gate).
5. **Seed `overrides.json`** from the current assignments: move the
   agent↔role bindings into `agent_assignment_overrides` (matthew/alex), and
   encode the existing `ROLE_SKILL_MAP` order as `skill_order_overrides` where
   the §9 deterministic order would otherwise differ.
6. **Populate all seven agents** by running the §11 coverage fallback; record
   the fallback choices in `overrides.json` so they become explicit, reviewable
   bindings.
7. **Consolidate vocabularies.** Map `PromptProfile.role` strings to role ids
   (or drop in favor of `capabilities`); keep a compat shim for one release.
8. **Move skill data** `BUILTIN_SKILL_DICTS` → `skills.json` (schema
   unchanged); `SKILL_CATEGORIES` → derived/`category` field on capabilities.
9. **Re-point** `runtime_context`, `agent_catalog`, and the UI at the effective
   view; run the full suite — all pre-existing tests must pass unchanged
   (behavior parity).
10. **Decommission literals** (`ROLE_SKILL_MAP`, `ROLE_CATEGORY_MAP`,
    `ROLE_SOURCES`, hand-written `AGENT_PRESETS`/`AGENT_CATEGORIES`) only after
    step 9 is green.
11. **Update docs/vault** (`AGENTS.md`, `README.md`, `sources/README.md`) to
    describe the *actual* derived pipeline.

## Backward compatibility shims (during transition)

- `roles.roles_for_agent` keeps reading `roles.json` until the matrix is the
  source of truth; a shim synthesizes the legacy view from the matrix.
- `prompt_library.suggest_prompts_for_role` stays as a deprecated wrapper over
  the capability-overlap resolver for one release.
- The `AgentPreset`/`AgentCategory` dataclass shapes are preserved so
  `agent_catalog.to_dict()` consumers (settings/routes/workspace) don't break.

## Source of truth / generated vs curated

Migration writes: `taxonomy.json` (generated), `overrides.json` (curated seed),
and the frontmatter evidence (curated). It edits `roles.json` only to add
`capabilities`/provenance fields (additive, non-destructive).

---

# 17. API Contracts

## New

| Endpoint | Purpose | Notes |
|---|---|---|
| `GET /api/taxonomy` | Effective taxonomy (repositories, evidence, capabilities, categories, role/skill/prompt edges, provenance) | read-only, effective view |
| `GET /api/taxonomy/coverage` | Matrix + `uncovered_agents`/`uncovered_capabilities` + fallback choices | drives §18 all-agent test |
| `POST /api/taxonomy/rebuild` | Regenerate `taxonomy.json` + effective view (never touches `overrides.json`) | operator-gated; returns drift/coverage report |
| `GET /api/taxonomy/status` | Drift status (sources dirty, orphaned overrides, last build) | for the Taxonomy view |

## Changed (shape-stable)

| Endpoint | Change |
|---|---|
| `GET /api/agent-catalog` | data source → effective taxonomy; same `{categories, presets}` shape |
| `GET /api/settings/role-categories` | derived categories instead of `ROLE_CATEGORY_MAP` |
| `GET /api/prompts` | profiles gain `capabilities` (already present) resolved against the vocabulary |
| `PUT /api/settings/agents/{agent}/roles|skills|prompts` | persist the **effective** result and mark overrides distinctly |
| `POST /api/settings/preset/{id}/apply` | writes an override (persistent) instead of only a designer node |

## Contract rules

- All list endpoints return **deterministic order** (category id, then
  capability id, then role/skill/profile id).
- Every entity in a taxonomy response includes `origin`/`source`/`license`
  provenance so the UI can render it.
- Overrides are returned with a `"derived": true|false` flag per field.

## Source of truth / generated vs curated

Endpoints read the effective view; only `rebuild` and the Settings
`PUT`/`POST` handlers mutate (and only the curated/derived files respectively).

---

# 18. Testing Strategy

## Unit tests

| Area | Tests |
|---|---|
| **Repository evidence** | frontmatter parse → `Repository`/`Evidence`; schema errors; `requires_inspection` flag; license extraction |
| **Capability identity** | stable id/name; provenance (non-original requires source); reverse indexes (role/skill/profile/agent) |
| **Taxonomy generation** | build from fixture sources → expected capabilities/categories/edges |
| **Deterministic regeneration** | build twice → byte-identical `taxonomy.json` (no timestamps) |
| **Overrides** | rename/merge; override wins; orphaned override → loud failure; rebuild never writes `overrides.json` |
| **Role/capability relationships** | role has multiple capabilities; capability in multiple roles; role→category derivation |
| **Skill/capability relationships** | role→skill via overlap equals fixture `ROLE_SKILL_MAP` (parity); no capability metadata duplicated in skill |
| **Prompt/capability relationships** | role→profile via overlap; two-vocabulary bridge removed |
| **Agent capability matrix** | every roster agent covered (≥1 role + skills/profiles); every capability covered; many-to-many both directions; fallback determinism |
| **Catalog generation** | derived presets from matrix; curated Empty Agent first; `validate_catalog` integrity |
| **Backward compatibility** | `AgentPreset.to_dict()`/`AgentCategory.to_dict()` shapes unchanged; `roles_for_agent` shim; `build_runtime_prompt` raw-request fallback |

## Integration / regression tests

| Test | Guarantee |
|---|---|
| **All-agent coverage** | for each of the 7 agents (read from `registry.py`, not typed), effective taxonomy yields ≥1 role + derived skills/profiles after build; `coverage.uncovered_agents == []` |
| **Repository-driven change** | adding a new source `.md` (or a capability block) changes derived capabilities/categories **without** editing `roles.json`/`agent_catalog.py` |
| **Override survival** | a curated override survives rebuild and still wins |
| **No cross-copy drift** | exactly one producing computation per role→skill / role→category edge (assert `ROLE_SKILL_MAP`/`ROLE_CATEGORY_MAP` literals are gone post-migration) |
| **Runtime propagation** | `build_runtime_prompt` renders the matrix-derived roles/skills/profiles for a previously-unconfigured agent; composition order + precedence unchanged |
| **UI API responses** | `agent-catalog`, `role-categories`, `prompt-categories` shapes stable while data source moves to the derived taxonomy |
| **Catalog generation** | preset for every matrixed agent; Empty Agent independent |
| **Provenance** | every non-original capability/role/skill/profile carries a source; adapted never marked original |

## The key replacing test

`test_every_existing_agent_is_used_by_at_least_one_preset` (audit §6.3) is
replaced by a **derived-coverage** assertion: after a build, every agent in the
roster is covered by the matrix, and coverage is recomputed (not asserted by
fiat). The test fails if the taxonomy stops covering an agent, rather than
passing only because someone typed all 7 keys.

---

# 19. Preliminary Capability Map

**Basis.** Derived strictly from the evidence already present in
`knowledge/sources/*.md` (read for this design) and the audit. **No
unsupported capability is invented.** Anything provisional is marked.

## Per-repository capabilities

| Repository | Evidence present | Proposed capabilities | Notes |
|---|---|---|---|
| `lfnovo/open-notebook` | source management, citation/reference handling, provenance, knowledge organization, research workflows, prompt transformations, model/provider abstraction | `source-management`, `citation`, `provenance`, `research-synthesis`, `knowledge-organization`, `prompt-transformation` | "prompt transformations" needs inspection to confirm it is a capability vs a workflow |
| `petergyang/no-ai-slop` | output-quality rules, editing, self-check, anti-generic | `output-quality`, `editing`, `self-review` | self-check ≈ `self-review` |
| `ayghri/i-have-adhd` | action-first, numbered, concise, state persistence, task decomposition | `action-first-communication`, `task-decomposition`, `concise-output` | state persistence may map to `context-continuity` (inspect) |
| `every-app/open-seo` | keyword research, clustering, competitive analysis, content workflows, agent-oriented tool use, MCP patterns | `keyword-research`, `search-intent`, `keyword-clustering`, `competitive-analysis`, `gap-analysis`, `content-strategy`, `tool-orchestration` | clustering could fold into `keyword-research` |
| `usestrix/strix` | recon, vuln discovery, validation/PoC, remediation, re-scan, security reporting, evidence-grounded findings, sandboxing, agent/tool boundaries | `security-reconnaissance`, `vulnerability-discovery`, `finding-validation`, `remediation`, `re-scan-verification`, `security-reporting`, `sandboxing` | `sandboxing` is infrastructure-adjacent (inspect scope) |
| `virgiliojr94/book-to-skill` | document→structured-skill extraction, indexing, framework/decision-rule/anti-pattern mining, on-demand loading, provenance-preserving reference | `knowledge-extraction`, `skill-authoring`, `indexing`, `distillation`, `provenance` (shared with open-notebook) | "on-demand loading" is an architectural pattern (inspect as capability) |
| `Anil-matcha/Open-Generative-AI` | multi-model/provider integration, self-hosted app architecture, model-agnostic tooling, provider-neutral selection | `multi-model-integration`, `provider-abstraction`, `generative-ai-app-development` | `provider-abstraction` overlaps open-notebook's model/provider abstraction |
| `NirDiamant/GenAI_Agents` | multi-agent orchestration (planner/workers, supervisor, router, reflection), planning, memory, tool use, routing, reflection, evaluation, RAG | `workflow-planning`, `multi-agent-orchestration`, `reflection`, `routing`, `evaluation` | **concepts only** (non-commercial license) — capabilities carry `origin: adapted`, no code/prompt text |

## Capabilities that emerge from >1 repository (dedup candidates)

- `provenance` — open-notebook + book-to-skill.
- `provider-abstraction` / `model-provider-abstraction` — open-notebook +
  Open-Generative-AI.
- `evaluation` — GenAI_Agents + strix (finding validation) + (internal
  `evaluation.py`).

## Clustering preview (illustrative, not authoritative)

The §7 clustering over these capabilities naturally produces domains such as
*research/knowledge*, *content/seo*, *security/verification*, *engineering/
orchestration*, and *communication/quality* — but these are **results of the
algorithm**, not assumptions. They may differ from the current 8 hard-coded
categories.

## Marked for repository inspection (not asserted)

- open-notebook: is `prompt-transformation` a capability or a workflow?
- i-have-adhd: does `context-continuity` (state persistence) belong as a
  capability?
- open-seo: are `keyword-clustering` and `keyword-research` distinct?
- strix: is `sandboxing` an in-scope capability or infrastructure?
- book-to-skill: is `on-demand-loading` a capability or an architectural
  pattern?
- Open-Generative-AI vs open-notebook: unify `provider-abstraction`?
- GenAI_Agents: which `reflection`/`routing`/`evaluation` concepts are
  capabilities vs skills vs profiles?

Each unresolved item becomes an `Evidence.requires_inspection: true` record so
the build ships the capability as **provisional** rather than silent.

---

# 20. Open Questions

1. **Primary binding granularity.** Should `agent → capability_ids` be the
   only curated binding (roles fully derived), or should `agent → role_ids`
   remain a first-class curated binding too? Proposal: capabilities primary,
   roles derived, with `agent_assignment_overrides.role_ids` as an escape
   hatch.
2. **Coverage fallback quality.** Is a deterministic domain-cluster fallback
   acceptable, or must every uncovered agent/capability require a human
   override before the build is considered clean? Proposal: fallback + loud
   `coverage` report; CI can fail on non-empty `uncovered_*` for strict repos.
3. **Where capability content lives.** Capability `name`/`description` are
   derived/seeded — but should their *canonical* text live in the evidence
   frontmatter (regenerable) or in `overrides.json` (curated)? Proposal:
   frontmatter seeds, overrides polish.
4. **Prompt `role` field fate.** Keep `PromptProfile.role` as an optional role
   id, or remove it entirely in favor of `capabilities`? Proposal: keep as
   optional role-id reference for one release, then deprecate.
5. **`roles.json` assignments vs matrix.** Do we keep `roles.json.assignments`
   as the runtime source (matrix synthesizes it) or invert (matrix is source,
   `roles.json` is seed)? Proposal: matrix is source after parity; a shim keeps
   `roles_for_agent` working.
6. **`agent_context.json` merge.** The existing skill/prompt assignment file
   (created lazily) overlaps the matrix's `agent_assignment_overrides`. Proposal:
   fold it into `overrides.json.agent_assignment_overrides` and keep a read
   shim for backward compatibility.
7. **Rebuild trigger.** Manual/operator-gated only, or also on startup drift
   detection? Proposal: manual + `status` drift check; never implicit rebuild.
8. **Non-evidence capabilities.** Are internal-project capabilities
   (`repository-analysis`, `code-review`) allowed with `origin: original` and no
   external repo? Proposal: yes — `origin: original`, `evidence` from
   "project architecture" (a reserved internal source id).

---

# 21. Implementation Phases

**Phase A — Evidence + Capability (no behavior change).**
Add frontmatter to `knowledge/sources/*.md`; add `scripts/core/taxonomy/`
(`evidence.py`, `capabilities.py`); extract the capability vocabulary; add
`Capability` provenance validation. No runtime wiring yet.

**Phase B — Taxonomy build (parity only).**
`build.py` produces `taxonomy.json` reproducing today's categories/roles/skills/
prompt edges; `overrides.py` + `effective.py`. Parity tests (§18) gate this
phase.

**Phase C — Re-point runtime.**
Replace `ROLE_SKILL_MAP`/`prompt_profiles_for_roles` with the capability-overlap
resolver; keep `build_runtime_prompt` signature + order + fallback. Full suite
green (behavior parity).

**Phase D — Agent capability matrix + coverage.**
`coverage.py`; seed all seven agents; derived-coverage tests replace the
hard-coded-coverage test.

**Phase E — Catalog redesign + persistence.**
`agent_catalog.py` becomes a resolver; preset application persists to
`overrides.json`; `validate_catalog` becomes a taxonomy-integrity check.

**Phase F — API + UI.**
`/api/taxonomy*` endpoints; Settings/Workspace consume derived data +
derived/override flags + Taxonomy view; remove hard-coded JS taxonomy literals.

**Phase G — Vocabulary consolidation + data extraction.**
Move `BUILTIN_SKILL_DICTS` → `skills.json`; consolidate prompt role/category
vocabularies; add compat shims.

**Phase H — Decommission + docs.**
Delete the redundant literals (`ROLE_SKILL_MAP`, `ROLE_CATEGORY_MAP`,
`ROLE_SOURCES`, hand-written `AGENT_PRESETS`/`AGENT_CATEGORIES`); update
`AGENTS.md`/`README.md`/`sources/README.md`.

Each phase is independently testable and lands green; no phase silently changes
dispatch behavior without a parity test.

---

## Appendix — Audit-finding closure map

| Audit finding | Addressed by |
|---|---|
| 5.1 no code reads reference repos | §4, §15 |
| 5.2 sources are prose, not parseable | §4 (frontmatter evidence) |
| 5.3 no `Capability` entity | §3 |
| 5.4 `project_profile` analyzes wrong repo | §2 P6 note: target-repo analysis stays separate; new taxonomy analyzer for reference repos |
| 6.1 only 2 agents configured | §11, §18 |
| 6.2 presets don't reach runtime | §12 (persistent apply), §13 |
| 6.3 test encodes hard-coding | §18 (derived-coverage test) |
| 7.1 role has no capability field | §8 |
| 7.2 two role vocabularies | §10 |
| 7.3 role metadata outside roles.json | §8 (fields move into role record/edges) |
| 7.4 role→skill duplicated | §9, P3 |
| 8/12 source-of-truth model | §5, §6 |
| 17 migration | §16 |

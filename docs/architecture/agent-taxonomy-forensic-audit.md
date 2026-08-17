# Agent Taxonomy — Forensic Audit

**Scope.** Audit of the **uncommitted** Agent Catalog / Role / Skill / Evaluation
implementation against the *intended* architecture: a **repository-driven,
capability-driven** taxonomy that derives a complete role/skill/prompt/agent
taxonomy from the capabilities and patterns of the seven reference repositories
(`lfnovo/open-notebook`, `petergyang/no-ai-slop`, `ayghri/i-have-adhd`,
`every-app/open-seo`, `virgiliojr94/book-to-skill`, `usestrix/strix`,
`Anil-matcha/Open-Generative-AI`), and applies that taxonomy to **all** agents.

**Verdict (headline).** The current implementation builds a *large, hand-written,
static* taxonomy. It is **not** repository-driven and **not** capability-driven:
the repositories are cited as string labels (`sources=("usestrix/strix", …)`) but
are never parsed, and there is **no `Capability` entity anywhere**. Categories,
roles, skills, prompt profiles, and presets are all hard-coded Python/data
literals. The architecture is *approximately* the right shape (roles ↔ skills ↔
prompt profiles are separated and composable), but the **derivation layer — the
piece the brief asks for — is missing entirely.**

No source code was modified for this audit.

---

# 1. Current Architecture

The runtime control plane has these layers (all under `scripts/core/`):

| Layer | Where it lives | Nature |
|---|---|---|
| **Agent identity** | `agents/*.py` (`AgentSpec`: tag/name/key only), `agents/registry.py` derives roster | Hard-coded identity, dynamic roster |
| **Agent runtime config** | `opencode.json` `agent.*` (model/mode/fallback/description) | Data file (runtime truth) |
| **Roles** | `roles.json` + `roles.py` | Data file (`$ZOVA_ROLES`), many-to-many |
| **Skills** | `skills.py` (`BUILTIN_SKILL_DICTS`) | Hard-coded Python built-in data |
| **Prompt profiles** | `prompt_library/builtin.py` + `prompt_library/profiles/*.py` | Hard-coded Python built-in data |
| **Evaluation** | `evaluation.py` (`BUILTIN_EVALUATION_DICTS`) | Hard-coded Python built-in data |
| **Categories / Presets** | `agent_catalog.py` | Hard-coded Python built-in data |
| **Capabilities** | *(no dedicated layer — see §3)* | Scattered string tuples |
| **Repository research** | `knowledge/sources/*.md` + `knowledge/sources/README.md` | Hand-written Markdown records |
| **Runtime composition** | `runtime_context.build_runtime_prompt()` | Canonical builder, used by RunHub, Orchestrator, planner |
| **Target-project analysis** | `project_profile.py` | Read-only scan of *this* repo (not the reference repos) |
| **UI** | `web_ui/settings.py`, `web_ui/routes.py`, `static/*.js` | Facade/API/frontend |

Execution paths that consume the taxonomy:

- **Terminal RunHub** — `run_hub.py::_run_agent` → `runtime_context.build_runtime_prompt(agent, user_request=…)`. Reads `roles.json` assignments + `agent_context.json` (absent) + `ROLE_SKILL_MAP` fallback.
- **Task Orchestrator** — `orchestrator.py::cmd_dispatch` → same builder, plus an optional task-level `role` frontmatter override.
- **Workflow planner** — `execution/planner.py::build_node_prompt` → same builder with per-node `roles`/`skills`/`instruction`.
- **Workflow Designer / Settings** — `agent_catalog.agent_catalog_data()` → sidebar preset library; selecting a preset materializes a `WorkflowNode` (`workspace.js::addNodeFromPreset`).

---

# 2. Current Uncommitted Changes

`git status` at audit time shows one coherent uncommitted change set. It is a
single "Phase 30 / Agent Catalog + Skill + Evaluation + Runtime Context"
implementation attempt (plus its doc/vault/tests). All of the following belong
to it:

**New (untracked) modules — the core of the attempt:**
- `scripts/core/agent_catalog.py` — categories + presets + role→category map.
- `scripts/core/skills.py` — the `Skill` registry (12 built-ins).
- `scripts/core/evaluation.py` — the `EvaluationDefinition` registry (3 built-ins).
- `scripts/core/runtime_context.py` — the canonical prompt builder + `ROLE_SKILL_MAP`.
- `test/tests/test_agent_catalog.py`, `test_skills.py`, `test_evaluation.py`,
  `test_runtime_context.py`, `test_task_execution.py`, `test/tests/home_*.test.js`.
- `workflows/template-seo-research.json`.
- `knowledge/sources/book-to-skill.md`, `knowledge/sources/open-generative-ai.md`.

**Modified (integrated into existing surfaces):**
- `roles.json` — added roles (`ai-agent-engineer`, `ai-llm-engineer`, `researcher`,
  `seo-researcher`, `seo-writer`, `technical-writer`, `knowledge-engineer`) and
  assignments (`matthew`, `alex`).
- `scripts/core/orchestrator.py`, `run_hub.py`, `execution/planner.py`,
  `workflows.py` — wired `runtime_context` + skills/evaluation into dispatch and
  workflow nodes.
- `scripts/web_ui/settings.py`, `routes.py` — exposed skills/prompts/catalog/role
  categories endpoints.
- `scripts/web_ui/static/settings.js`, `workspace.js`, `app.js`, `app.css`,
  `index.html` — Settings pickers + catalog sidebar.
- `scripts/vault_validate.py` — task status vocabulary.
- Docs/vault: `AGENTS.md`, `README.md`, `knowledge/README.md`,
  `knowledge/sources/README.md`, `obsidian_vault/*`, `state.md`.

**Not part of this attempt (pre-existing, committed baseline):** the agent
identity specs (`scripts/core/agents/*.py`), `opencode.json` model config,
`project_profile.py`, the prompt library, model registry/connections, and the
workflow/execution engine.

**Observation.** `agent_context.json` (the persistence file `runtime_context.py`
reads/writes for per-agent skill/prompt assignments) **does not exist** in the
working tree. It is created lazily only when a user edits assignments via the
Settings API. So by default the only agent-specific context is `roles.json`
assignments + the hard-coded `ROLE_SKILL_MAP`.

---

# 3. Hardcoded Taxonomy

Everything below is a **hand-written literal**, not derived from any repository.

| File | Symbol | What is hard-coded |
|---|---|---|
| `scripts/core/agent_catalog.py` | `AGENT_CATEGORIES` | 8 `AgentCategory` entries (ai, research, content, documentation, development, devops, security, testing). `sources` is a **string tuple**, not a lookup. |
| `scripts/core/agent_catalog.py` | `AGENT_PRESETS` | 14 `AgentPreset` entries, each pinning a role + ordered skills + ordered prompt profiles + one of the 7 agent keys. |
| `scripts/core/agent_catalog.py` | `ROLE_CATEGORY_MAP` | role id → single category (14 entries). |
| `scripts/core/agent_catalog.py` | `ROLE_SOURCES` | role id → evidence-source strings (14 entries). |
| `scripts/core/runtime_context.py` | `ROLE_SKILL_MAP` | role id → ordered skill ids (15 entries). This is the *only* role→skill knowledge the runtime has. |
| `scripts/core/skills.py` | `SKILL_CATEGORIES`, `BUILTIN_SKILL_DICTS` | 8 skill categories; 12 skills with `capabilities`/`steps`/provenance literals. |
| `scripts/core/skills.py` | `_SKILL_KEYWORDS` | task-text → skill keyword mapping (12 entries). |
| `scripts/core/prompt_library/schema.py` | `PROMPT_ROLES` (14), `CATEGORIES` (14) | prompt-role + category vocabularies. |
| `scripts/core/prompt_library/task.py` | `TASK_CATEGORIES` (15), `_CATEGORY_RULES`, `_CAPABILITY_KEYWORDS`, `_TASK_KEYWORD_PROMPTS` | task classification + role/capability inference. |
| `scripts/core/prompt_library/registry.py` | `_KEYWORDS` | role/agent-key → prompt-role mapping. |
| `scripts/core/prompt_library/profiles/*.py` | all profile dicts | ~49 prompt profiles, each with `capabilities` literals. |
| `scripts/core/project_profile.py` | `_TECH_ROLES`, `_UNIVERSAL_ROLES`, `_MANIFEST_SIGNALS` | technology → role suggestion map (target-repo only). |
| `scripts/core/model_registry/builtin.py`, `prompt_library/model_capabilities.py` | model capability profiles | model capability archetypes (out of taxonomy scope but also static). |

**Hard-coded cross-references (duplication risk):**

- `ROLE_SKILL_MAP` (runtime_context.py) duplicates the role→skills knowledge
  that is **also** written out per-preset in `AGENT_PRESETS`. Two copies must be
  kept in sync by hand. (Currently they agree; nothing guarantees it.)
- `ROLE_CATEGORY_MAP` and `ROLE_SOURCES` (agent_catalog.py) hold role metadata
  that lives **outside** `roles.json` — `roles.json` has no `category` or
  `source` field.
- Prompt-profile `role` values (`software_engineer`) are a **different
  vocabulary** from `roles.json` role ids (`python-developer`). The bridge is
  keyword heuristics (`suggest_prompts_for_role`).

---

# 4. Dynamic Taxonomy

The only things actually *derived* at runtime (vs. hand-written):

- **Roster** — `agents/registry.py` derives `AGENTS`/`TABS` from the 7 specs.
- **Role assignments** — read live from `roles.json` (`roles.roles_for_agent`).
- **Skill / prompt assignments** — read live from `agent_context.json`
  (`runtime_context.load_agent_context`), when the file exists.
- **Role → skill union** — `runtime_context.skills_for_roles` expands
  `ROLE_SKILL_MAP` (but the map itself is static).
- **Role → prompt suggestion** — `prompt_library.suggest_prompts_for_role`
  (keyword map; static).
- **Task → role/skill/prompt suggestions** — keyword classifiers (static rules).
- **Target-project role suggestions** — `project_profile.analyze_repository`
  scans *this* repo's manifests (static `_TECH_ROLES`).

None of these derive anything **from the reference repositories**.

---

# 5. Repository-Driven Gaps

**The intended chain is:** `Repository → Capability → Role → Skill → Prompt
Profile → Agent`. The current code implements the **right half** of that chain
(Role/Skill/Prompt/Agent) as static data, and the **left half** (Repository →
Capability) is missing.

Finding 5.1 — **No code reads the reference repositories.**

- **File:** (none) — grep for `knowledge/sources` shows no parser.
- **Relevant code:** `agent_catalog.py` `AgentCategory.sources`, `ROLE_SOURCES`.
- **Current behavior:** `sources` is a display/citation string, e.g.
  `AgentCategory("documentation", …, ("virgiliojr94/book-to-skill",))`. It is
  written by hand at development time.
- **Why it is a problem:** adding a repository, or re-reading one, has **zero
  effect** on the taxonomy. The "repository-driven" claim in `AGENTS.md`/`README.md`
  is not backed by code.
- **Proposed direction:** introduce a repository-analysis module that reads a
  machine-parseable form of `knowledge/sources/*.md` (or a structured
  `repository_catalog.json` generated from them), extracts
  `capabilities`/`patterns`/`integration targets`, and feeds a taxonomy build.

Finding 5.2 — **The knowledge records are human prose, not parseable inputs.**

- **File:** `knowledge/sources/*.md` (e.g. `book-to-skill.md`,
  `open-generative-ai.md`).
- **Relevant fields:** `Useful concepts:`, `Recommended integration target:`,
  `Useful architectural patterns:` are free-text bullets.
- **Current behavior:** `knowledge/sources/README.md` maintains a manual
  "reference map" table (Source → pattern → internal target → implementation).
- **Why it is a problem:** the mapping is a documentation artifact, not an
  executable pipeline. It can drift from `agent_catalog.py` with nothing to
  detect it.
- **Proposed direction:** add a structured, versioned capability record per
  source (JSON or YAML frontmatter in the `.md`), and a build step that consumes
  it. Keep the prose for humans, add machine fields for the pipeline.

Finding 5.3 — **There is no `Capability` entity.**

- **File:** grep `capabilit` → only `PromptProfile.capabilities`,
  `Skill.capabilities`, `TaskProfile.capabilities`, `ModelCapabilityProfile`.
- **Current behavior:** capabilities are free-form string tuples attached to
  three *different* objects, with no shared vocabulary, no id, no source link.
- **Why it is a problem:** capability is the proposed join key between a
  repository and its roles/skills/prompts. Without a first-class `Capability`,
  "capability-driven" can't be implemented, and role→skill derivation is forced
  to be a hard-coded `ROLE_SKILL_MAP`.
- **Proposed direction:** first-class `Capability` records (id, name,
  description, source repos, evidence). Roles, skills, and prompt profiles
  reference capability ids; role→skill derivation becomes capability overlap.

Finding 5.4 — **`project_profile.py` analyzes the wrong repository.**

- **File:** `scripts/core/project_profile.py`.
- **Relevant code:** `analyze_repository()` scans the **target workspace**
  (`PROJECT_ROOT`) for tech signals and suggests roles.
- **Current behavior:** it never opens the seven reference repositories.
- **Why it is a problem:** it conflates "analyze the repo the *user* is coding
  in" with "analyze the *reference* repositories to build the taxonomy". The
  brief's "repository-driven" means the latter.
- **Proposed direction:** keep `project_profile` for target-repo context, add a
  separate `taxonomy/repository_analysis.py` for the reference repos.

---

# 6. Agent Coverage Gaps

Finding 6.1 — **Only 2 of 7 agents have runtime roles.**

- **File:** `roles.json` → `assignments`.
- **Relevant code:** `roles.roles_for_agent(agent)`.
- **Current behavior:** `matthew → [python-developer, code-reviewer]`,
  `alex → [software-architect, security-engineer]`. `sarah`, `david`, `elena`,
  `max`, `chloe` have **no** roles.
- **Why it is a problem:** `build_runtime_prompt` falls back to `roles.json`
  assignments. Those five agents therefore receive **raw requests** on the
  terminal/orchestrator paths (no identity/role/skill/profile), unless a
  workflow node or preset is explicitly applied.
- **Proposed direction:** the derived taxonomy must assign capabilities/roles to
  **all** agents, not a hand-picked subset; coverage of "every agent receives
  appropriate context" must be a testable invariant.

Finding 6.2 — **Presets do not reach the terminal/orchestrator runtime.**

- **File:** `scripts/core/agent_catalog.py` (`build_preset_runtime_prompt`),
  `run_hub.py`, `orchestrator.py`.
- **Relevant code:** `run_hub._run_agent` and `orchestrator.cmd_dispatch` call
  `build_runtime_prompt(agent, …)` directly — **never** `build_preset_runtime_prompt`.
- **Current behavior:** a preset is only materialized when the user drags it
  into the Workflow Designer (`workspace.js::addNodeFromPreset` → a node with
  explicit `roles`/`skills`/`prompt_profile`) or when tests call
  `build_preset_runtime_prompt` directly. Selecting a preset in Settings does not
  bind it to the agent persistently.
- **Why it is a problem:** the catalog looks like it "configures" agents but is
  effectively a **template library for the workflow designer**, disconnected
  from the agent's persistent context. "Apply preset to agent X" has no
  persistent effect.
- **Proposed direction:** presets should resolve **into** the persistent
  context (roles.json / agent_context.json) or be a first-class resolved view,
  not a parallel island.

Finding 6.3 — **The "every agent used by a preset" test encodes the current
hard-coding.**

- **File:** `test/tests/test_agent_catalog.py::ExistingAgentsPreservedTestCase`.
- **Relevant code:** `test_every_existing_agent_is_used_by_at_least_one_preset`
  asserts `used == set(EXISTING_AGENTS)`.
- **Current behavior:** the 7-agent coverage is a side effect of hand-picking
  `agent_key` on each preset.
- **Why it is a problem:** the test *documents* the hard-coded subset as if it
  were a derived guarantee. It would pass trivially only because someone typed
  all 7 keys once.
- **Proposed direction:** replace with a test that every agent is covered by the
  **derived** taxonomy, and that coverage is recomputed, not asserted by fiat.

---

# 7. Role / Skill / Prompt Separation

The separation is **mostly sound** at the data-shape level:

- `Role` (`roles.json`): expertise — responsibilities/tools/permissions/rules/
  expected outputs. **No `capabilities`, no `category`, no `source`.**
- `Skill` (`skills.py`): operating procedure — `steps` + `capabilities` +
  optional `prompt_profile` composition + provenance. Good.
- `PromptProfile` (`prompt_library/schema.py`): mindset — `role`/`category`/
  `prompt` text + `capabilities` + provenance. Good.

Problems:

Finding 7.1 — **Role has no capability field, breaking the chain.**

- **File:** `scripts/core/roles.py` (`Role` dataclass), `roles.json`.
- **Why it is a problem:** the brief's chain is
  `Capability → Role → Skill → Prompt`. If roles can't declare capabilities,
  role→skill and role→prompt must be a hard-coded map (`ROLE_SKILL_MAP`,
  `suggest_prompts_for_role`).
- **Proposed direction:** add `capabilities` (and provenance `source`/`origin`)
  to the role record so role→skill/profile can be derived by capability overlap.

Finding 7.2 — **Two vocabularies for "role".**

- **File:** `prompt_library/schema.py` `PROMPT_ROLES` vs `roles.json` ids.
- **Relevant code:** `prompt_library.registry._KEYWORDS` bridges them by
  keyword (`"developer" → software_engineer`).
- **Current behavior:** `python-developer` (role store) ≠ `software_engineer`
  (prompt role). The bridge is fragile substring matching.
- **Why it is a problem:** the role/skill/prompt layers can't share a single
  capability/role vocabulary, so cross-layer derivation is heuristic, not
  structural.
- **Proposed direction:** one canonical role/capability vocabulary that both
  `roles.json` and prompt profiles reference (prompt `role` becomes a role id or
  is removed in favor of `capabilities`).

Finding 7.3 — **Role metadata lives outside `roles.json`.**

- **File:** `agent_catalog.py` `ROLE_CATEGORY_MAP` + `ROLE_SOURCES`.
- **Current behavior:** category and evidence for a role are Python literals.
- **Why it is a problem:** the role store is incomplete; the "taxonomy" half of
  a role is divorced from its "expertise" half.
- **Proposed direction:** move `category`/`source`/`capabilities` into the role
  record (or a derived taxonomy overlay), not a separate map.

Finding 7.4 — **Role→skill knowledge is duplicated.**

- **File:** `runtime_context.py` `ROLE_SKILL_MAP` vs `agent_catalog.py`
  `AGENT_PRESETS[*].skills`.
- **Why it is a problem:** the same "researcher needs structured-research +
  source-verification" is stated twice; drift is silent.
- **Proposed direction:** single derivation source (capability overlap), presets
  and runtime both read it.

---

# 8. Proposed Source-of-Truth Model

**One persistent, regenerable taxonomy store, layered over the existing
registries — not replacing them.**

```
knowledge/sources/*.md          (human research records; add machine fields)
        │  (build step: repository analysis)
        ▼
knowledge/taxonomy/taxonomy.json  ← THE DERIVED SOURCE OF TRUTH (regenerable)
        │  (curated overlay, never regenerated)
        ▼
knowledge/taxonomy/overrides.json ← manual curation / user overrides
        │
        ▼
Runtime registry (roles.json + skills.py + prompt_library + catalog)
```

- **Regenerable layer** (`taxonomy.json`): repositories, capabilities, categories,
  and *derived* role/skill/prompt references — produced by a deterministic build
  from the source records. Never hand-edited.
- **Curated layer** (`overrides.json`): what a human pinned or changed (agent →
  role/skill/profile assignments, renamed categories, capability overrides).
  Layered *on top of* the derived layer; survives rebuild.
- **Effective view** = derived ⊕ overrides. This is what `runtime_context`,
  `agent_catalog`, and the UI consume.

Agents and models stay where they are today (that part is correct and should not
move): `scripts/core/agents/*.py` for identity, `opencode.json` for model/mode/
fallback.

---

# 9. Repository → Capability → Role → Skill → Prompt → Agent Model

Target end-state (to be built later; **not implemented now**):

```text
Reference repository (license + patterns)
        │  analyze → extract
        ▼
Capability (id, name, description, source repos, evidence)   ← NEW entity
        │  capabilities compose
        ▼
Role          (expertise + references capabilities + provenance)
Skill         (procedure + references capabilities)
Prompt Profile (mindset + references capabilities/role)
        │  resolution: capability overlap, not hard-coded maps
        ▼
Agent (identity, model)  ←  assigned one-or-many roles/skills/profiles
        │
        ▼
runtime_context.build_runtime_prompt()   (unchanged composition order)
```

Current state of each edge:

| Edge | Status |
|---|---|
| Repository → Capability | **Missing** (no parser, no capability entity) |
| Capability → Role | **Missing** (roles have no capability field) |
| Capability → Skill | **Partial** (skills have `capabilities`, but no shared vocabulary) |
| Capability → Prompt | **Partial** (profiles have `capabilities`, no shared vocabulary) |
| Role → Skill | **Hard-coded** (`ROLE_SKILL_MAP`) |
| Role → Prompt | **Heuristic** (`suggest_prompts_for_role`) |
| Role/Skill/Prompt → Agent | **Partial** (roles.json + agent_context.json + presets) |

---

# 10. What to Keep

- **`scripts/core/agents/*.py` + `registry.py` + `__main__.py verify`** — the
  identity-only roster and its drift check are correct and match the intended
  decoupling. Keep unchanged.
- **`opencode.json` model/mode/fallback + `opencode_cfg.resolve_model`** — models
  remain a runtime concern; correct.
- **`roles.py` many-to-many assignment model** (`assignments`, `roles_for_agent`,
  precedence constant, `render_role_context`). The *mechanism* is right; only the
  *content* (no capabilities/category/provenance, sparse assignments) is lacking.
- **`skills.py` `Skill` schema** (steps + capabilities + provenance + validation)
  — a good building block; keep the schema, move its *contents* to data.
- **`prompt_library/schema.py` `PromptProfile` + provenance (`source`/`license`/
  `origin`)** — keep the schema and provenance discipline.
- **`runtime_context.build_runtime_prompt()`** — the single canonical composition
  builder and its precedence (explicit > agent assignment > role-derived) and its
  backward-compatible raw-prompt fallback. Keep; **re-point** its `ROLE_SKILL_MAP`
  and `prompt_profiles_for_roles` at the derived taxonomy.
- **`evaluation.py`** — well-isolated, provenance-aware, deterministic; not part
  of the taxonomy problem. Keep.
- **`knowledge/sources/*.md` + `sources/README.md` license matrix** — the right
  seed material; augment with machine fields rather than discard.
- **`workflows.py` node schema** (`roles`/`skills`/`prompt_profile`/`evaluation`
  references) — the right composition surface.
- **`project_profile.py`** — keep, but scoped to target-repo context, distinct
  from reference-repo taxonomy analysis.

---

# 11. What to Redesign

- **`agent_catalog.py` — redesign entirely.** Remove `AGENT_CATEGORIES`,
  `AGENT_PRESETS`, `ROLE_CATEGORY_MAP`, `ROLE_SOURCES` as hand-written literals.
  Replace with a resolver that reads the derived taxonomy + overrides and
  produces categories/presets **deterministically** (presets become
  "role+skills+profiles bound to an agent" *derived* from capability coverage,
  not typed per row).
- **`runtime_context.py` `ROLE_SKILL_MAP` + `prompt_profiles_for_roles`** — move
  to the derived capability-overlap resolver.
- **`skills.py` `BUILTIN_SKILL_DICTS` / `SKILL_CATEGORIES`** — move to data
  (regenerable), keep the `Skill` schema + registry.
- **`prompt_library` `PROMPT_ROLES`/`CATEGORIES`/`_KEYWORDS`/`task.py` rules** —
  consolidate into one canonical role/capability vocabulary driven by the
  taxonomy, eliminating the role-id vs prompt-role two-vocabulary bridge.
- **`roles.json` role records** — add `capabilities`, `category`(or drop in favor
  of derived grouping), and provenance fields. Populate assignments for **all 7**
  agents from the derived taxonomy (not just matthew + alex).
- **`agent_catalog.py` ↔ `runtime_context.py` ↔ Settings preset application** —
  unify preset selection so it *persists* into roles.json / agent_context.json
  instead of being a designer-only template island.
- **`knowledge/sources/*.md`** — add a machine-parseable capability/pattern
  block and a `taxonomy` build step (new module), so the map is rebuilt, not
  hand-maintained.

---

# 12. Required Data Model

Proposed entities (names indicative; final naming TBD at implementation):

```text
Capability {
  id, name, description,
  source_repos: [repo_id],        # evidence
  origin: original|adapted,
}
Repository {
  id, url, license,
  extracted_capabilities: [capability_id],
  patterns: [str],                # human-readable, for traceability
}
Role {
  id, name, description,
  capabilities: [capability_id],  # NEW
  category: str | derived,        # NEW
  responsibilities/tools/permissions/rules/expected_outputs,  # keep
  source/ license/ origin,        # NEW (provenance, as skills/prompts have)
}
Skill {
  id, name, steps, capabilities: [capability_id], prompt_profile?, provenance
}
PromptProfile {
  id, name, prompt, capabilities: [capability_id], role?, provenance
}
AgentAssignment {                 # effective (derived ⊕ overrides)
  agent_key: str,
  role_ids: [..], skill_ids: [..], prompt_profile_ids: [..],
}
Taxonomy {
  schema_version,
  repositories, capabilities, roles, skills, prompt_profiles, categories,
  agent_assignments,
  generated_at,
}
Overrides {                       # curated, never regenerated
  capability/role/category overrides,
  agent_assignment overrides,
}
```

Key rules:
- `Capability` is the join key; `Role.capabilities` ∩ `Skill.capabilities`
  drives role→skill; `Role.capabilities` ∩ `PromptProfile.capabilities` drives
  role→prompt. No more `ROLE_SKILL_MAP`.
- `Taxonomy` is the **regenerable** truth; `Overrides` is the **curated** truth;
  effective = `Taxonomy ⊕ Overrides`.

---

# 13. Required API Changes

- `GET /api/agent-catalog` — serve the **derived** categories/presets (from the
  effective taxonomy) instead of the hard-coded tuple; same shape so the
  frontend contract is stable.
- `GET /api/settings/role-categories` — derive from the taxonomy, not
  `ROLE_CATEGORY_MAP`.
- New: `GET /api/taxonomy` (or `/api/capabilities`) — expose the derived
  capability/repository graph for the UI to show *why* a role/skill exists.
- New: `POST /api/taxonomy/rebuild` — regenerate `taxonomy.json` from
  `knowledge/sources` (operator-gated; never silently rewrites overrides).
- `PUT /api/settings/agents/{agent}/roles|skills|prompts` — keep, but persist the
  **effective** (derived + override) result and mark overrides distinctly.
- `POST /api/settings/preset/{id}/apply` (or extend the existing preset flow) —
  apply a preset so it *writes* into roles.json / agent_context.json, not just a
  designer node.
- New: `GET /api/taxonomy/coverage` — which agents have which capabilities
  (drives the §16 coverage tests).
- Existing `/api/prompts`, `/api/models`, `/api/settings/*` stay; only their
  data source changes.

---

# 14. Required UI Changes

- **Catalog sidebar** (`workspace.js`): render categories/presets from the
  derived taxonomy; show capability badges + provenance on each preset card so
  the repository origin is visible, not a hidden string.
- **Settings → Roles/Skills/Prompts** (`settings.js`): category grouping and
  pickers read the derived vocabulary; show "derived" vs "overridden" state for
  each assignment (so a user knows what a rebuild will or won't touch).
- **New/updated view:** a "Taxonomy" or "Capabilities" tab listing
  `Repository → Capability → Role/Skill/Prompt` with rebuild status and drift
  warnings (e.g. a source `.md` whose capability block changed since last build).
- **Preset application** must visibly persist (an "Apply to agent" affordance)
  rather than only producing a workflow node.

---

# 15. Required Runtime Changes

- `runtime_context.build_runtime_prompt` — keep the signature and ordering, but
  resolve effective skills/profiles from the **effective taxonomy** (capability
  overlap) instead of `ROLE_SKILL_MAP` / `suggest_prompts_for_role`.
- `agent_catalog.build_preset_runtime_prompt` / `resolve_preset_config` — resolve
  against the derived taxonomy; `validate_catalog` becomes a taxonomy-integrity
  check (capabilities resolve, categories derived, all agents covered).
- `run_hub`, `orchestrator`, `planner` — no signature changes; they keep calling
  `build_runtime_prompt`. Their behavior improves automatically once the builder
  reads the derived taxonomy.
- Provenance rendering (`render_prompt_profile_context`,
  `render_skill_context`) — surface the *capability* and *repository* origin,
  consistent with today's source/license output.

---

# 16. Required Tests

Guarantee the brief's invariants:

1. **All-agent coverage** — for each of the 7 agents, the effective taxonomy
   yields ≥1 role (and its derived skills/profiles); assert no agent is
   "unconfigured" after a taxonomy build. (Replaces
   `test_every_existing_agent_is_used_by_at_least_one_preset`.)
2. **Determinism/idempotence** — rebuilding `taxonomy.json` twice yields
   byte-identical output (no timestamps in the derived layer).
3. **Repository → capability extraction** — adding a new `knowledge/sources/*.md`
   record (or a new capability block) changes the derived capabilities/categories
   **without** editing roles.json / agent_catalog.py.
4. **Override survival** — a curated override survives a rebuild and still wins
   over the derived value.
5. **Many-to-many** — one capability appears in multiple roles/agents; one agent
   holds multiple roles/capabilities; union is deduplicated and order-stable.
6. **Capability-driven role→skill/profile** — `Role.capabilities` ∩
   `Skill.capabilities` yields the same skills as today's `ROLE_SKILL_MAP`
   (migration parity), then continues to work when a skill is added.
7. **No cross-copy drift** — assert there is exactly **one** source for each
   role→skill and role→category edge (kill the duplication between
   `ROLE_SKILL_MAP` and `AGENT_PRESETS`).
8. **Vocabulary coherence** — `roles.json` ids, prompt `role`s, and capabilities
   resolve through one canonical vocabulary (no keyword bridge regressions).
9. **Provenance** — every non-original role/skill/prompt/capability carries a
   source; adapted sources are never marked original.
10. **Runtime composition unchanged** — the §7 ordering, precedence, and
    raw-request backward-compatibility tests keep passing after the re-point.
11. **API contract** — `agent-catalog`, `role-categories`, `prompt-categories`
    shapes stay stable while the data source moves to the derived taxonomy.

---

# 17. Migration Strategy

1. **Freeze.** Keep the current hard-coded registries as the *seed* for the
   derived data; do not delete them yet.
2. **Machine-fy the sources.** Add structured capability/pattern blocks to
   `knowledge/sources/*.md` (or generate `repository_catalog.json` from them) for
   the 7 reference repos.
3. **Introduce `Capability`** and a `taxonomy/build.py` that produces
   `taxonomy.json` from those sources, initially reproducing today's
   categories/roles/skills/prompts (so a rebuild equals the current literals —
   parity gate).
4. **Add `overrides.json`** and the `effective = derived ⊕ overrides` resolver.
5. **Re-point** `runtime_context` (skill/profile resolution) and `agent_catalog`
   (categories/presets) at the effective taxonomy; run the full suite — all
   existing tests (§2) must pass unchanged (behavior parity).
6. **Persist preset application** into roles.json / agent_context.json; remove
   the designer-only island.
7. **Populate all 7 agents** from the derived taxonomy; add the coverage tests.
8. **Decommission** the now-redundant literals (`ROLE_SKILL_MAP`,
   `ROLE_CATEGORY_MAP`, `ROLE_SOURCES`, hand-written `AGENT_PRESETS`).
9. **Docs/vault** — update `AGENTS.md`/`README.md`/`sources/README.md` to
   describe the *actual* (derived) pipeline, not the aspirational one.

---

# 18. Risks

- **Scope creep / rewrite temptation.** The instinct will be to "rebuild from
  scratch." Mitigation: keep `build_runtime_prompt`, `AgentSpec`, `roles.py`
  mechanisms, `prompt_library`/`skills` schemas, and `evaluation.py` (§10); only
  the derivation + data placement changes.
- **Behavior regression.** Re-pointing the builder could silently change prompts
  for the 2 currently-configured agents. Mitigation: the parity gate in §17.5
  (existing tests green before/after).
- **Drift between prose and machine fields.** The `.md` records can get out of
  sync with `taxonomy.json`. Mitigation: a `check-conflicts`-style drift check
  (like `knowledge_sync`) and a rebuild-status marker.
- **Overrides silently clobbered.** A rebuild that overwrites curation would
  destroy user intent. Mitigation: strict separation of regenerable vs curated
  files; rebuild refuses to write `overrides.json`.
- **Vocabulary unification cost.** Collapsing `PROMPT_ROLES` + `roles.json` ids +
  capabilities touches many modules and tests. Mitigation: do it as its own
  step (§17.7) with a compat shim.
- **License/provenance compliance.** Non-original content must keep source/
  license/origin. Mitigation: keep the existing `validate_*` provenance rules
  and extend them to the new `Capability`/`Role` records.
- **Seven-agent assumption baked into tests.** Tests asserting `== {7 agents}` or
  `used == EXISTING_AGENTS` will mask a taxonomy that stops covering all agents.
  Mitigation: replace with derived-coverage assertions (§16.1).
- **Two "repository analysis" concepts collide.** `project_profile.py`
  (target repo) vs the new taxonomy analyzer (reference repos) must be kept
  distinct or future work will re-conflate them (§5.4).

---

## Appendix A — Audit-question index

| Q | Where answered |
|---|---|
| 1. Source of truth for each concept | §1, §3, §4, §8 |
| 2. Hardcoded parts | §3 |
| 3. Dynamically derived parts | §4 |
| 4. Does the catalog derive categories from repo capabilities? | §5.1–5.3 (no) |
| 5. Does the system derive roles from repository analysis? | §5.1, §5.3 (no; missing layer) |
| 6. All agents or a subset? | §6.1–6.3 (subset) |
| 7. Role/Skill/Prompt separated? | §7 (mostly; gaps 7.1–7.4) |
| 8. Clean Repository→…→Agent distinction? | §9 (no; left half missing) |
| 9. One capability → many agents? | §6, §12, §16.5 (not yet; no capability entity) |
| 10. One agent → many roles/capabilities? | §6.1, §16.5 (roles yes; capabilities no) |
| 11. Categories evolve with new repos? | §5.1, §5.2 (no; manual) |
| 12. Preserve curated overrides? | §8, §12, §16.4, §18 (no mechanism yet) |
| 13. Violations of intended architecture | §5, §6, §7, §9 |
| 14. What to keep | §10 |
| 15. What to redesign | §11 |
| 16. What in roles.json should not be hardcoded | §7.3, §11, §12 |
| 17. Persistent source of truth for the derived taxonomy | §8, §12 |
| 18. Rebuild without rewriting roles | §8, §12, §17 |
| 19. How the UI consumes it | §14 |
| 20. How runtime_context consumes it | §15 |
| 21. How presets are generated/resolved | §9, §11, §15 |
| 22. Tests guaranteeing all agents get capabilities | §16 |

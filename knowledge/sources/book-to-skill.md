---
id: book-to-skill
source_url: https://github.com/virgiliojr94/book-to-skill
license: MIT
source_type: open-source methodology
extraction_mode: ideas
code_reuse: concepts only
domains: [knowledge, documentation]
evidence:
  - id: structured-skill-extraction
    kind: methodology
    summary: Distill documents into structured skills with indexed rules and provenance.
    supports: [knowledge-extraction, skill-authoring, indexing, distillation, provenance]
    confidence: direct
    requires_inspection: true
---
# virgiliojr94/book-to-skill

- **Repository:** `virgiliojr94/book-to-skill`
- **URL:** https://github.com/virgiliojr94/book-to-skill
- **License:** MIT (LICENSE.md)
- **Source type:** Agent skill (converts documents into a reusable, on-demand agent skill)
- **Main purpose:** Turn a technical book, document folder, or collection of
  sources into a unified, on-demand agent skill — structure, not a summary.
- **Important directories/files:** `SKILL.md` (extraction spec), `scripts/extract.py`
  (deterministic document extractor), `docs/` (how-it-works, performance,
  usage), generated `chapters/`, `glossary.md`, `patterns.md`, `cheatsheet.md`.
- **Useful concepts:** document → structured skill extraction; chapter/section
  indexing; framework, decision-rule, and anti-pattern mining; on-demand loading
  to keep answers proportional to the question; provenance-preserving reference.
- **Useful prompts/skills:** "extract structure, not a summary" distillation;
  deterministic extraction plus spec-driven generation.
- **Useful workflow patterns:** extract → structure (index/glossary/patterns) →
  load on demand → cite from real content.
- **Useful architectural patterns:** separate a deterministic extractor from the
  spec-driven generator; keep reference units small and lazily loaded; treat a
  generated skill as a reusable, provenance-aware asset.
- **MultiAgentCoding integration:** grounds the `knowledge-extraction` Skill
  (adapted, in our own words) and the `knowledge-engineer` role/preset in the
  Agent Catalog. Nothing is imported; the extraction procedure is re-expressed
  using native Skill abstractions.
- **Recommended integration target:** Skill + Role/Category taxonomy
  (Documentation / Knowledge).
- **License restrictions:** MIT — preserve copyright/notice in any reuse.
- **Code reuse allowed:** Yes (with license notice preserved) — we adapt the
  procedure, not the code.
- **Extraction mode:** Ideas / procedure (no code or prompt text copied).

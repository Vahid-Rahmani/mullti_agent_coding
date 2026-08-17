---
id: open-notebook
source_url: https://github.com/lfnovo/open-notebook
license: MIT
source_type: open-source application
extraction_mode: ideas
code_reuse: concepts only
domains: [research, knowledge-management]
evidence:
  - id: citation-discipline
    kind: pattern
    summary: Separate source claims from AI interpretation and preserve citations.
    supports: [source-management, citation, provenance]
    confidence: direct
    requires_inspection: false
  - id: reusable-sources
    kind: architecture
    summary: Keep sources as reusable first-class assets for research workflows.
    supports: [source-management, knowledge-organization, research-synthesis]
    confidence: direct
    requires_inspection: false
---
# lfnovo/open-notebook

- **Repository:** `lfnovo/open-notebook`
- **URL:** https://github.com/lfnovo/open-notebook
- **License:** MIT
- **Source type:** Open-source application (self-hosted NotebookLM alternative)
- **Main purpose:** AI-assisted research, note-taking, and knowledge management
  with source handling, citations, and prompt transformations.
- **Important directories/files:** backend + frontend app structure; source
  management and citation modules; prompt/transformation flows.
- **Useful concepts:** knowledge architecture, research workflows, source
  management, citation/reference handling, prompt transformations,
  model/provider abstraction, knowledge organization.
- **Useful prompts/skills:** source-aware summarization and synthesis with
  explicit provenance and citation.
- **Useful workflow patterns:** research → source collection → synthesis →
  cited output, with sources reusable across projects.
- **Useful architectural patterns:** keep sources as first-class, reusable
  assets; separate a source's claim from the AI's interpretation.
- **MultiAgentCoding integration:** informs the Obsidian-based persistent
  knowledge system (source provenance, citation discipline) and the
  `research-source-manager` prompt profile. Obsidian is **not** replaced.
- **Recommended integration target:** Knowledge + Prompt Library.
- **License restrictions:** MIT — preserve copyright/notice in any reuse.
- **Code reuse allowed:** Yes (with license notice preserved) — we adapt
  concepts and write original code/text.
- **Extraction mode:** Ideas / concepts (no code copied).

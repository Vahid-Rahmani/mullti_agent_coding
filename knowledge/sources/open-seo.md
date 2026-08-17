---
id: open-seo
source_url: https://github.com/every-app/open-seo
license: MIT
source_type: open-source application
extraction_mode: ideas
code_reuse: concepts only
domains: [content, research]
evidence:
  - id: seo-research-workflow
    kind: workflow
    summary: Combine keyword research, clustering, intent, and competitive analysis.
    supports: [keyword-research, search-intent, keyword-clustering, competitive-analysis, gap-analysis, content-strategy, tool-orchestration]
    confidence: direct
    requires_inspection: true
---
# every-app/open-seo

- **Repository:** `every-app/open-seo`
- **URL:** https://github.com/every-app/open-seo
- **License:** MIT
- **Source type:** Open-source SEO toolkit (self-hosted, agent-oriented)
- **Main purpose:** Open-source alternative to Semrush/Ahrefs with pre-built
  skills for keyword research, backlinks, rank tracking, and site audits.
- **Important directories/files:** skills directory, docs (self-hosting),
  MCP/tool integrations.
- **Useful concepts:** SEO workflows, keyword research, keyword clustering,
  competitive analysis, content workflows, agent-oriented tool usage, workflow
  composition, MCP patterns.
- **Useful prompts/skills:** keyword-research and competitive-analysis
  methodologies.
- **Useful workflow patterns:** keyword research → clustering → competitive
  analysis → content analysis → audit.
- **Useful architectural patterns:** skills as composable, self-contained tool
  wrappers around an agent.
- **MultiAgentCoding integration:** `seo-keyword-research` and
  `seo-competitive-analysis` prompt profiles plus the `seo-research` workflow
  template (built on the existing Workflow Graph / Engine). No SEO code is
  imported into core.
- **Recommended integration target:** Prompt Library + Workflow Template.
- **License restrictions:** MIT — preserve copyright/notice in any reuse.
- **Code reuse allowed:** Yes (with license notice preserved) — we adapt the
  methodology, not the code.
- **Extraction mode:** Ideas / methodologies (no code copied).

---
id: no-ai-slop
source_url: https://github.com/petergyang/no-ai-slop
license: MIT
source_type: open-source guidance
extraction_mode: ideas
code_reuse: concepts only
domains: [communication, quality]
evidence:
  - id: anti-generic-output
    kind: output-policy
    summary: Apply editing and self-check rules to avoid generic output.
    supports: [output-quality, editing, self-review]
    confidence: direct
    requires_inspection: false
---
# petergyang/no-ai-slop

- **Repository:** `petergyang/no-ai-slop`
- **URL:** https://github.com/petergyang/no-ai-slop
- **License:** MIT
- **Source type:** Skill (single-purpose editing skill + rules)
- **Main purpose:** Removes 20+ patterns of "AI slop" from writing without
  flattening the author's voice.
- **Important directories/files:** skill definition (SKILL.md / prompt), LICENSE.
- **Useful concepts:** output-quality rules, writing rules, self-check rules,
  anti-generic-output rules.
- **Useful prompts/skills:** editing instructions that cut filler, formulaic
  transitions, and canned conclusions while preserving voice.
- **Useful workflow patterns:** write → self-edit → review pass.
- **Useful architectural patterns:** an output-quality policy that can be
  attached to any writing/reviewing role.
- **MultiAgentCoding integration:** converted into the `writer-anti-slop`
  prompt profile (a reusable output-quality policy), assignable to workflow
  nodes or roles.
- **Recommended integration target:** Prompt Library.
- **License restrictions:** MIT — preserve copyright/notice in any reuse.
- **Code reuse allowed:** Yes (with license notice preserved) — we adapt the
  rules into our own profile text.
- **Extraction mode:** Ideas / rules (no prompt text copied).

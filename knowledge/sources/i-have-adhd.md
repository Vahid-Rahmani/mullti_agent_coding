---
id: i-have-adhd
source_url: https://github.com/ayghri/i-have-adhd
license: MIT
source_type: open-source guidance
extraction_mode: ideas
code_reuse: concepts only
domains: [communication, execution]
evidence:
  - id: action-first-communication
    kind: output-policy
    summary: Prefer concise numbered action-first communication without tangents.
    supports: [action-first-communication, task-decomposition, concise-output]
    confidence: direct
    requires_inspection: false
---
# ayghri/i-have-adhd

- **Repository:** `ayghri/i-have-adhd`
- **URL:** https://github.com/ayghri/i-have-adhd
- **License:** MIT
- **Source type:** Skill (a short rules file for coding agents)
- **Main purpose:** Stops a coding agent from burying the answer; action-first,
  ADHD-friendly output.
- **Important directories/files:** `skills/i-have-adhd/SKILL.md`, README, INSTALL.
- **Useful concepts:** action-first responses, state persistence, numbered
  steps, reducing unnecessary explanations, context continuity, clear next
  actions, managing long tasks, avoiding tangents.
- **Useful prompts/skills:** concise output rules that lead with the result and
  end with the single next action.
- **Useful workflow patterns:** answer-first report → numbered steps → next
  action.
- **Useful architectural patterns:** an output policy that composes with any
  agent, independent of role or model.
- **MultiAgentCoding integration:** converted into the
  `communicator-action-first` prompt profile, using native MultiAgentCoding
  abstractions (not external code).
- **Recommended integration target:** Prompt Library (output policy).
- **License restrictions:** MIT — preserve copyright/notice in any reuse.
- **Code reuse allowed:** Yes (with license notice preserved) — we adapt the
  conventions into our own profile text.
- **Extraction mode:** Ideas / conventions (no prompt text copied).

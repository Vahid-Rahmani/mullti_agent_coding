# External Knowledge & Prompt Intelligence — Source Registry

This directory is the **external knowledge / reference layer**. Each upstream
repository researched for MultiAgentCoding has one source record (a sibling
`.md` file) capturing its license, purpose, useful concepts, and the
integration decision. These are **research/reference sources**, not runtime
dependencies — the MultiAgentCoding architecture remains independently
implementable and never imports an external repository.

## License matrix

| Repository | License | Code reuse status | Integration status |
| --- | --- | --- | --- |
| `NirDiamant/GenAI_Agents` | Custom (non-commercial) | No code reuse — concepts only | Knowledge + prompt + skill (independently written) |
| `lfnovo/open-notebook` | MIT | Allowed with attribution/notice | Knowledge + prompt + skills + evaluation (adapted) |
| `petergyang/no-ai-slop` | MIT | Allowed with attribution/notice | Prompt + skill (adapted) |
| `ayghri/i-have-adhd` | MIT | Allowed with attribution/notice | Prompt + skill (adapted) |
| `every-app/open-seo` | MIT | Allowed with attribution/notice | Prompts + skills + workflow template |
| `usestrix/strix` | Apache-2.0 | Allowed with attribution/notice | Prompt + skills + workflow template + evaluation |
| `Anil-matcha/Open-Generative-AI` | MIT | Allowed with attribution/notice | Role/category taxonomy (`ai-llm-engineer`) |
| `virgiliojr94/book-to-skill` | MIT | Allowed with attribution/notice | Skill (`knowledge-extraction`) + role/category taxonomy (`knowledge-engineer`) |
| `book` | — (not located) | n/a | Unresolved (documented, not fabricated) |

## Reference map

How each external source flows into internal components:

```text
External Source
      ↓
Knowledge Entry (knowledge/sources/<source>.md)
      ↓
Pattern (concept, workflow, or output policy)
      ↓
Prompt / Skill / Role / Category / Workflow Template / Evaluation
      ↓
Implementation (scripts/core/prompt_library, scripts/core/skills,
                scripts/core/workflows, scripts/core/evaluation,
                scripts/core/agent_catalog)
```

| Source | Extracted pattern | Internal target | Implementation |
| --- | --- | --- | --- |
| `GenAI_Agents` | multi-agent planning / routing / reflection | Prompt Library (`ai_engineer`) | `agent-workflow-planner` profile |
| `open-notebook` | source management + citation discipline | Prompt Library (`researcher`) | `research-source-manager` profile |
| `no-ai-slop` | output-quality / anti-generic rules | Prompt Library (`technical_writer`) | `writer-anti-slop` profile |
| `i-have-adhd` | action-first, numbered, no tangents | Prompt Library (`orchestrator`) | `communicator-action-first` profile |
| `open-seo` | keyword research / competitive analysis | Prompt Library + Workflow Template | `seo-keyword-research`, `seo-competitive-analysis` profiles; `seo-research` template |
| `strix` | find → validate → fix → re-scan → report | Prompt Library + Skill + Workflow Template + Evaluation | `security-pentest-validator` profile; `security-reconnaissance`, `security-validation`, `fix-verify-loop` skills; `security-audit` template; `security-findings-quality` evaluation |
| `open-notebook` | source management + citation discipline | Prompt Library + Skill + Evaluation | `research-source-manager` profile; `structured-research`, `source-verification` skills; `research-output-quality` evaluation |
| `no-ai-slop` | output-quality / anti-generic rules | Prompt Library + Skill | `writer-anti-slop` profile; `anti-slop-refinement` skill |
| `i-have-adhd` | action-first, numbered, no tangents | Prompt Library + Skill | `communicator-action-first` profile; `action-first-communication` skill |
| `open-seo` | keyword research / competitive analysis | Prompt Library + Skill + Workflow Template | `seo-keyword-research`, `seo-competitive-analysis` profiles; `seo-research`, `competitive-analysis` skills; `seo-research` template |
| `GenAI_Agents` | multi-agent planning / routing / reflection | Prompt Library + Skill | `agent-workflow-planner` profile; `workflow-planning` skill (concepts only) |
| `Open-Generative-AI` | multi-model / provider-neutral integration | Role/Category taxonomy | `ai-llm-engineer` role + preset (AI Engineering) |
| `book-to-skill` | document → structured-skill extraction | Skill + Role/Category taxonomy | `knowledge-extraction` skill; `knowledge-engineer` role + preset (Documentation / Knowledge) |

The Knowledge system answers *"Why does this feature exist and which external
research influenced its design?"* without making the runtime depend on the
external repository.

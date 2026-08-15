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
| `NirDiamant/GenAI_Agents` | Custom (non-commercial) | No code reuse — concepts only | Knowledge + prompt concept (independently written) |
| `lfnovo/open-notebook` | MIT | Allowed with attribution/notice | Knowledge + prompt profile (adapted) |
| `petergyang/no-ai-slop` | MIT | Allowed with attribution/notice | Prompt profile (adapted) |
| `ayghri/i-have-adhd` | MIT | Allowed with attribution/notice | Prompt profile (adapted) |
| `every-app/open-seo` | MIT | Allowed with attribution/notice | Prompt profiles + workflow template |
| `usestrix/strix` | Apache-2.0 | Allowed with attribution/notice | Prompt profile + workflow template |
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
Prompt / Skill / Role / Workflow Template
      ↓
Implementation (scripts/core/prompt_library, scripts/core/workflows)
```

| Source | Extracted pattern | Internal target | Implementation |
| --- | --- | --- | --- |
| `GenAI_Agents` | multi-agent planning / routing / reflection | Prompt Library (`ai_engineer`) | `agent-workflow-planner` profile |
| `open-notebook` | source management + citation discipline | Prompt Library (`researcher`) | `research-source-manager` profile |
| `no-ai-slop` | output-quality / anti-generic rules | Prompt Library (`technical_writer`) | `writer-anti-slop` profile |
| `i-have-adhd` | action-first, numbered, no tangents | Prompt Library (`orchestrator`) | `communicator-action-first` profile |
| `open-seo` | keyword research / competitive analysis | Prompt Library + Workflow Template | `seo-keyword-research`, `seo-competitive-analysis` profiles; `seo-research` template |
| `strix` | find → validate → fix → re-scan → report | Prompt Library + Workflow Template | `security-pentest-validator` profile; `security-audit` template |

The Knowledge system answers *"Why does this feature exist and which external
research influenced its design?"* without making the runtime depend on the
external repository.

---
type: system
status: active
owner: all
created: 2026-08-11
updated: 2026-08-17
related: [System_Core, Architecture_Home, Agents_Home, Tasks_Home, Testing_Home]
---

# Dashboard — MultiAgentCoding

> **Control plane knowledge graph — entry point.**
> Human-authored header: edit freely. The section below between the GENERATED
> markers is rebuilt by `python scripts/generate_dashboard.py`.

- ↑ Root: [[System_Core]]
- Navigate: [[Architecture_Home]] · [[Agents_Home]] · [[Tasks_Home]] · [[Decisions_Home]] · [[Documentation_Home]] · [[Testing_Home]]

---

<!-- GENERATED: dashboard -->
## Project Status
- **Vault:** 45 managed nodes · schema validated
- **Task lifecycle:** [[Tasks_Home]] · [[Task_Backlog]]
- **Agents:** [[Agents_Home]] · **Architecture:** [[System_Architecture]]

## Active / In-Progress Tasks
| Task | Status |
|---|---|
| [[Task_Docs_Audit]] | planned |
| [[Task_Skill_Evaluation_Extraction]] | completed |
| [[Task_Vault_Health_Check]] | ready |
| [[Task_WebUI_Smoke_Test]] | ready |

**Counts:** planned=1, ready=2, in_progress=0, blocked=0, completed=1, failed=0

## Active Agents
- [[Agent_Alex]] — google/gemini-3.6-flash
- [[Agent_Chloe]] — opencode/ling-3.0-tiny-free
- [[Agent_David]] — opencode/big-pickle
- [[Agent_Elena]] — opencode/ling-3.0-tiny-free
- [[Agent_Matthew]] — opencode/deepseek-v4-flash-free
- [[Agent_Max]] — google/gemini-3.1-flash-lite
- [[Agent_Sarah]] — opencode/deepseek-v4-flash-free

## Recent Executions
**Orchestrator log (last 5):**

- `[2026-08-17T11:12:02] set-status Task_Demo: ready -> in_progress`
- `[2026-08-17T11:12:02] set-status Task_Demo: planned -> ready`
- `[2026-08-17T11:12:02] set-status Task_Demo: ready -> in_progress`
- `[2026-08-17T11:12:02] report Task_Demo: recorded failed`
- `[2026-08-17T11:12:02] set-status Task_Demo: planned -> ready`

**Sync log (last 3):**

- `{"ts": "2026-08-17T10:42:55", "mode": "sync", "dry_run": true, "actions": [], "conflicts": []}`
- `{"ts": "2026-08-17T10:46:10", "mode": "sync", "dry_run": true, "actions": [], "conflicts": []}`
- `{"ts": "2026-08-17T11:11:53", "mode": "sync", "dry_run": true, "actions": [], "conflicts": []}`

## Recent Changes
**Vault changes (last 3):**

- _(no recorded vault changes)_

## Testing Status
- See [[Testing_Home]] and [[Test_Report_Suite]] — current suite: `python -m unittest discover -s test/tests`

## Architecture Status
- Map: [[System_Architecture]]
- **O2 components:** [[Component_Orchestrator]] · [[Component_VaultBridge]] · [[Component_ContextResolver]] · [[Component_ChangeDetector]] · [[Component_KnowledgeSync]]
- **O2 component gaps:** _None — all five nodes are mapped._
- **Repository taxonomy:** 55 capabilities · 14 categories · 7/7 agents covered · effective overrides available in the Taxonomy UI

## Blocked / Needs Attention
- _None currently — see [[Task_Backlog]] for full status._
<!-- /GENERATED -->

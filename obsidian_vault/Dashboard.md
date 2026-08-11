---
type: system
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
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
- **Vault:** 36 managed nodes · schema validated
- **Task lifecycle:** [[Tasks_Home]] · [[Task_Backlog]]
- **Agents:** [[Agents_Home]] · **Architecture:** [[System_Architecture]]

## Active / In-Progress Tasks
| Task | Status |
|---|---|

**Counts:** planned=0, ready=0, in_progress=0, blocked=0, completed=0, failed=0

_No task nodes yet — see [[Task_Backlog]]._

## Active Agents
- [[Agent_Alex]] — opencode/deepseek-v4-flash-free
- [[Agent_Chloe]] — opencode/ling-3.0-tiny-free
- [[Agent_David]] — opencode/big-pickle
- [[Agent_Elena]] — opencode/ling-3.0-tiny-free
- [[Agent_Matthew]] — opencode/deepseek-v4-flash-free
- [[Agent_Max]] — opencode/deepseek-v4-flash-free
- [[Agent_Sarah]] — opencode/deepseek-v4-flash-free

## Recent Executions
**Orchestrator log (last 5):**

- `[2026-08-11T19:49:15] set-status Task_Demo: ready -> in_progress`
- `[2026-08-11T19:49:15] set-status Task_Demo: planned -> ready`
- `[2026-08-11T19:49:15] set-status Task_Demo: ready -> in_progress`
- `[2026-08-11T19:49:15] report Task_Demo: recorded failed`
- `[2026-08-11T19:49:15] set-status Task_Demo: planned -> ready`

**Sync log (last 3):**

- `{"ts": "2026-08-11T19:48:49", "mode": "sync", "dry_run": true, "actions": [], "conflicts": []}`
- `{"ts": "2026-08-11T19:49:02", "mode": "sync", "dry_run": true, "actions": [], "conflicts": []}`
- `{"ts": "2026-08-11T19:49:13", "mode": "sync", "dry_run": true, "actions": [], "conflicts": []}`

## Recent Changes
**Vault changes (last 3):**

- `{"ts": "2026-08-11T19:49:15", "caller": "test", "node": "C:\\Users\\meins\\AppData\\Local\\Temp\\tmp99c9hc6y\\vault\\03-`
- `{"ts": "2026-08-11T19:49:15", "caller": "test-caller", "node": "C:\\Users\\meins\\AppData\\Local\\Temp\\tmp8yx47ayq\\vau`
- `{"ts": "2026-08-11T19:49:15", "caller": "test", "node": "C:\\Users\\meins\\AppData\\Local\\Temp\\tmpurgyzn2a\\vault\\03-`

## Testing Status
- See [[Testing_Home]] and [[Test_Report_Suite]] — current suite: `python -m unittest discover -s test/tests`

## Architecture Status
- Map: [[System_Architecture]]
- **Known gaps (reported by `knowledge_sync check-conflicts`, not auto-fixed):**
- `orchestrator.py` — real module with no `Component_*` node yet
- `vault_bridge.py` — real module with no `Component_*` node yet
- `context_resolver.py` — real module with no `Component_*` node yet
- `change_detector.py` — real module with no `Component_*` node yet
- `knowledge_sync.py` — real module with no `Component_*` node yet

## Blocked / Needs Attention
- _None currently — see [[Task_Backlog]] for full status._
<!-- /GENERATED -->

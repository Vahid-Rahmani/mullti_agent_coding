# Roadmap — MultiAgentCoding Control Plane

> **Last updated:** 2026-08-11 10:30 UTC
> **Current branch:** `full`

---

## Phase A — Foundation: Swarm Coordinator Core

- [x] `scripts/swarm.py` — pure-stdlib coordinator (state, labels, stale scan, claim, feedback, brief, CLI)
- [x] Per-slot role state persisted in `_logs/swarm/m<slot>.json`
- [x] Feedback JSONL in `_logs/swarm_feedback.jsonl`
- [x] Dynamic title builder (`M3-Helper->M1`)
- [x] Tests: `test/tests/test_swarm.py` (23 tests)

## Phase B — Launcher Integration

- [x] `scripts/run_agent_worker.ps1` — swarm loop with stale-peer detection + atomic claim
- [x] Domain-preserving helper takeover (peer's agent identity + model)
- [x] Live window-title updates
- [x] Swarm-brief prepend to task prompts
- [x] Prompt sanitization (`ConvertTo-SafeTask`, `--` guard)
- [x] `launch_agents.bat` — `--no-swarm` + `--stale N` flags + usage text

## Phase C — Tests & Test Infrastructure

- [x] `test/tests/test_swarm.py` — 23 swarm tests
- [x] `test/tests/test_terminal_app.py` — 75 terminal tests (replaced web/GUI tests)
- [x] `test_expense_manager.py` — sys.path fix retained
- [x] Full suite green: `python -m unittest discover -s test/tests` → 264 tests OK

## Phase D — UI: Terminal App Refactoring & Styling

- [x] Remove `web_app.py`, `unified_app.py`, `supervisor.py`, `restart_web.ps1`, `launch_web.bat`
- [x] Ship `scripts/terminal_app.py` — ZOVA retro terminal (rich + prompt_toolkit)
- [x] Strict 4-color CRT theme (white / orange / grey / neon-green on black)
- [x] ASCII ZOVA banner
- [x] Directory status indicator
- [x] Agent tab bar (MASTER + M1–M7 with live status dots)
- [x] Model status bar
- [x] Scrollable per-tab console
- [x] Rounded interactive prompt box
- [x] Slash commands: `/help /cd /model /mode /agents /status /clear /stop /swarm /proposals /evolve /quit`
- [x] `launch_terminal.bat` + `.vscode/tasks.json` update
- [x] **Terminal app refactoring for unified loading bar** (current branch)
- [x] Weighted progress aggregation across all agents (master bar)
- [x] Session tag tracking for idle-bar reset
- [x] Half-up rounding fix for progress display (62.5 → 63%)
- [x] Single-row loading window (remove extra newline gap)
- [x] Clear + terminate reset all session state
- [ ] Code review + merge of `feature/ui-loading-refactor`

## Phase E — Security & Hygiene (BLOCKER)

- [ ] Remove hardcoded `9router` provider block from `opencode.json` (embedded API key)
- [ ] Verify `git grep -n 'sk-'` returns nothing on tracked files
- [ ] Ensure `__pycache__/*.pyc` and `.pyc` diffs are not committed
- [ ] Clean `git status --short` of `_logs/` / `_inbox/` artifacts

## Phase F — Verification & Ship

- [ ] Full E2E pass: swarm CLI smoke, worker smoke, launcher dry run
- [ ] `launch_agents.bat --dry --smoke` exits cleanly
- [ ] Headless terminal: `python scripts/terminal_app.py --smoke` exits 0
- [ ] Final commit + reviewer approval + merge to `main`

---

## Backlog / Future

- [ ] Web SSE endpoints for live swarm role events (deferred)
- [ ] Desktop GUI notebook tab renaming + digest prepend (deferred)
- [ ] `opencode.json` model-fallback tuning
- [ ] Knowledge re-indexing automation
- [ ] Prompt template library in [[prompts/]]
- [ ] Agent run history archive in [[agents_logs/]]
---

## Audit Status (M7 — Obsidian-Vault-Sync)

- **Last audit:** 2026-08-10 07:33 UTC
- **Branch:** `feature/obsidian-vault-integration`
- **Uncommitted changes:** 6 file(s) modified
- **Completed runs:** 21
- **Prompt logs:** 26

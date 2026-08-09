# PLAN.md — Dynamic Swarm Role-Swapping & Peer-Assistance Protocol

> **Checkpoint (2026-08-09):** Core implementation is complete and green
> (264 tests OK). This plan is reconciled with the **actual implemented design**,
> which evolved from the original draft (module name, CLI shape, default
> polarity). Remaining work: security fix (hardcoded API key in `opencode.json`),
> final E2E verification, and commit/review.
>
> **UI migration (2026-08-09):** the web UI (`web_app.py`) and desktop GUI
> (`unified_app.py`) were **removed** and replaced by a single full-screen retro
> terminal, `scripts/terminal_app.py` (ZOVA). See `test/tests/test_terminal_app.py`
> (75 tests). The swarm protocol below is unaffected; the terminal reuses the
> same run machinery and adds `/swarm`, `/evolve`, and `/proposals` commands.

## Objective

Upgrade the `opencode run` execution layer — the 7-window launcher
(`launch_agents.bat` + `scripts/run_agent_worker.ps1`), the web workspace
(`scripts/web_app.py`), and the desktop GUI (`scripts/unified_app.py`) — with a
cooperative swarm protocol providing three behaviors:

1. **Role rotation on completion** — when a worker finishes its own task it
   becomes a *Swarm Helper* and takes over stale (unclaimed) tasks from lagging
   peers instead of idling.
2. **Dynamic tab/window renaming** — the cooperative role and its assistance
   target are encoded in a live window title (`M3-Helper->M1`) and persisted per
   slot so any UI can reflect it.
3. **Inter-agent learning & feedback loop** — every run (own or assisted)
   appends a JSONL feedback record; a deterministic "swarm brief" is prepended
   to the next task prompt so agents share context across cycles.

The `opencode run` invocation itself (flags, agent names, models) stays
unchanged; the protocol wraps it with role state, labels, and shared context.

## Scope

**In scope (implemented)**
- NEW `scripts/swarm.py` — pure-stdlib swarm coordinator module (CLI
  subcommands `title`, `find-stale`, `claim`, `feedback`, `brief`, `state`,
  `swarm`). Per-slot role state in `_logs/swarm/m<slot>.json`; feedback JSONL in
  `_logs/swarm_feedback.jsonl`; dynamic title builder `M3-Helper->M1`.
- `scripts/run_agent_worker.ps1` — swarm loop: stale-peer detection, atomic
  claim, domain-preserving helper takeover (executes peer task with the peer's
  agent identity), live window-title updates, feedback records, swarm-brief
  prepend, and prompt sanitization (`ConvertTo-SafeTask`, `--` guard for
  dash-leading prompts). Swarm **ON by default**; `-NoSwarm` opt-out.
- `launch_agents.bat` — `--no-swarm` and `--stale N` flags + usage text.
- `scripts/terminal_app.py` — `_after_self_evolve_run` exception guard
  (watcher must never crash the loop), `_sanitize_prompt` + `--` guard for
  option-like prompts (exit-code-1 fix) — **migrated from the removed
  `web_app.py` / `unified_app.py`**. The web and GUI layers were deleted with
  this migration (see UI migration note).
- Tests: NEW `test/tests/test_swarm.py` (23 tests); NEW
  `test/tests/test_terminal_app.py` (75 tests) replaces `test_web_app.py` /
  `test_unified_app.py` / `test_supervisor.py`; `test_expense_manager.py`
  (sys.path fix) retained.
- `README.md` — swarm protocol documentation.
- `opencode.json` — **cleanup required**: remove the `9router` provider block
  that embeds a hardcoded API key (security).

**Out of scope (descoped at this checkpoint)**
- Web `GET /api/swarm`, SSE `role` events, and dynamic nav/label re-render
  (original T6/T7) — the web app received only the watcher guard. Deferred.
- Desktop notebook tab renaming + digest prepend in `unified_app.py` (original
  T8) — GUI received only prompt sanitization. Deferred.
- `opencode.json` agents/providers/auth — no changes except the secret removal.
- Hive internals (`.hive/`), `knowledge/` re-indexing, `AGENTS.md` wording.

## Key decisions (actual, supersede earlier draft wording)

1. **Module name/CLI** — `scripts/swarm.py` with subcommand CLI
   (`find-stale`/`claim`/`feedback`/`brief`/`state`/`title`), not the drafted
   `swarm_coordinator.py` with `--rotate/--label/--status` flags. The worker
   shells out to subcommands; JSON/B64 payloads cross the boundary.
2. **Stale-based takeover, not completion-based rotation** — an idle worker
   periodically scans `_inbox/` for peer tasks unclaimed for `--stale N`
   seconds (default 20); `claim` atomically renames the file so the first
   helper wins. No shared queue; preserves the decentralized launcher design.
3. **Swarm ON by default, `-NoSwarm` opt-out** — inverted from the original
   draft's `-Swarm` opt-in; keeps the feature active with zero launcher flags.
4. **Domain-preserving takeover** — a helper runs a claimed peer task with the
   peer's opencode agent (`--agent <peer>`), logs into the peer's
   `_logs/<peer>.log`, and marks the done file as taken over.
5. **Pure stdlib coordinator** — no third-party deps; paths injectable for tests.
6. **Security hard rule** — never commit secrets. The `9router` provider block
   in `opencode.json` (added during implementation with an embedded API key)
   MUST be removed before merge; keys live only in
   `~/.local/share/opencode/auth.json`.

## Current state (verified 2026-08-09)

- `python -m unittest discover -s test/tests` → **264 tests OK** (incl. 23 new
  `test_swarm.py` tests).
- `scripts/swarm.py` CLI functional: `find-stale`, `claim`, `feedback`, `brief`,
  `state`, `title` all unit-tested.
- Worker script swarm integration present (`-NoSwarm`, `-NoBrief`,
  `-StaleSeconds`, `-MaxHelpers`, `-HelpCoolDown`).
- `launch_agents.bat --dry` prints swarm-enabled commands; `--no-swarm`,
  `--stale N` wired.
- **Uncommitted**: entire swarm feature + test updates + README sit in the
  working tree on branch `feature/auto-learning-setup` (ahead of origin by 4).
- `_inbox/` empty; `state.md` Phase: running; 21 finish records.

## Remaining work (this checkpoint)

- **R1 (BLOCKER, security)** — remove the `9router` provider block from
  `opencode.json` (embedded API key `sk-…` inside `{env:…}`). Verify no secrets
  remain (`git grep sk-` empty), config still parses, agents/models intact.
- **R2 (verification)** — full E2E pass: run the complete suite, swarm CLI
  smoke (`--status`-equivalent subcommands with temp inbox), worker smoke with a
  seeded fake task + peer takeover marker, headless web check, `launch_agents.bat
  --dry/--smoke`, and `git status --short` clean of `_logs/`/`_inbox/` artifacts.
- **R3 (hygiene)** — ensure `__pycache__/*.pyc` and `.pyc` diffs are not
  committed (they are tracked; consider adding to `.gitignore`/`git rm --cached`
  in a separate commit or leave pre-existing tracking untouched — reviewer
  call).
- **R4 (commit + review)** — commit the swarm feature (single-purpose commits),
  then route through reviewer for approval and merge to `main` per AGENTS.md.

## Epics

- **E1 — Swarm coordinator (`swarm.py`)** — DONE: state, labels, stale scan,
  claim, feedback, brief, CLI.
- **E2 — Launcher integration** — DONE: worker swarm loop, takeover, live
  titles, bat flags, prompt hardening.
- **E3 — Tests** — DONE: `test_swarm.py` + web/GUI/expense test updates; suite
  green.
- **E4 — Security & hygiene** — PENDING: remove hardcoded API key; keep runtime
  artifacts out of git.
- **E5 — Verification & ship** — PENDING: E2E pass, commit, review, merge.

## Phases

- **Phase A — Foundation (E1)**: DONE
- **Phase B — Launcher (E2)**: DONE
- **Phase C — Tests (E3)**: DONE
- **Phase D — Security & hygiene (E4)**: R1 → R3 (next: R1, backend-dev)
- **Phase E — Verify & ship (E5)**: R2 → R4 (tester, then reviewer)

## Definition of Done

- Full suite: `python -m unittest discover -s test/tests -v` exits 0.
- No secrets: `git grep -n 'sk-'` on tracked files returns nothing;
  `opencode.json` parses and all agent model mappings intact.
- Worker smoke: seeded fake task in a temp inbox completes; a peer takeover
  moves `_inbox/<peer>.task` to `done/` with the taken-over marker; window title
  reflects the helper role.
- `launch_agents.bat --dry` prints swarm commands; `--smoke --no-swarm` still
  exits cleanly.
- Headless terminal: `python scripts/terminal_app.py --smoke` exits 0
  (SMOKE-OK); `GET /api/swarm` no longer applies (web removed).
- `git status --short` clean of runtime artifacts (`_logs/`, `_inbox/`);
  feature committed on `feature/auto-learning-setup`; reviewer approved.

## Verification Commands

- `python -m unittest discover -s test/tests -v`
- `python scripts/swarm.py find-stale --inbox _inbox --own planner --stale 5`
- `python scripts/swarm.py claim --inbox _inbox --agent frontend-dev --by 4`
- `python scripts/swarm.py feedback --file _logs/swarm_feedback.jsonl --slot 4 --agent backend-dev --mode helper --target 5 --ok true --duration 1 --task smoke`
- `python scripts/swarm.py brief --file _logs/swarm_feedback.jsonl --swarm _logs/swarm`
- `python scripts/swarm.py state --swarm _logs/swarm --slot 3 --json '{"status":"helper"}'; python scripts/swarm.py swarm --swarm _logs/swarm`
- `powershell -File scripts/run_agent_worker.ps1 -Agent planner -Slot 3 -Smoke`
- `launch_agents.bat --dry [--no-swarm]`
- `git grep -n 'sk-' -- ':!_logs' ':!_inbox'` (expect empty)
- `git status --short`
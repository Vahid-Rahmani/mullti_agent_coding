---
type: architecture
status: active
owner: architect
created: 2026-08-11
updated: 2026-08-11
related: [System_Architecture, Component_RunHub]
---

# Component_StateTracker

> Session state persistence — reads/writes the workspace `state.md` checkpoint.

**Type:** architecture · **Status:** active (`[E]` existing) · **Owner:** architect

---

## Purpose

Persists run phase, last-run metadata, completion log, decisions, pending
modifications, and restart log to `state.md`. All writes are atomic
(temp file + `os.replace`) so a crash never leaves a half-written state file.

## Source (verified)

- `scripts/core/state_tracker.py` — `StateTracker` class + module-level `STATE`

## Responsibilities

- `record_run(prompt, started)` / `record_finish(tag, ok)` / `record_restart(...)`
- Compress the `## Completed` section beyond 20 entries
- Parse and render the `## Section` format of `state.md`
- Thread-safe via an internal lock

## Dependencies

- [[Component_AgentSpecs]] — `PROJECT_ROOT` (state file location)
- Standard library (json, os, tempfile, threading)

## Input / Output

- **Input:** run/finish/restart events from [[Component_RunHub]]
- **Output:** `state.md` at the workspace root

## Links

- ↑ Parent: [[System_Architecture]]
- ↔ Related: [[Component_RunHub]]

# AGENTS.md — MultiAgentCoding Control Plane

This repository is the **control plane** for a self-evolving multi-agent coding
system. It holds the MultiAgentCoding configuration, agent definitions, skills,
and memory used to drive software projects (typically under `projects/`).

## Roles

| Agent | Role | Model |
|---|---|---|
| `matthew` | Matthew — lead architecture + master coordination (read-only) | opencode/deepseek-v4-flash-free |
| `alex` | Alex — backend, APIs, Python logic, and data handling | opencode/deepseek-v4-flash-free |
| `sarah` | Sarah — TUI, frontend, UX, and rendering | opencode/deepseek-v4-flash-free |
| `david` | David — QA, TDD, tests, and debugging | opencode/big-pickle |
| `elena` | Elena — code quality and security audit (read-only) | opencode/ling-3.0-tiny-free |
| `max` | Max — DevOps, automation, and environment stability | opencode/deepseek-v4-flash-free |
| `chloe` | Chloe — documentation and Obsidian knowledge audit (read-only) | opencode/ling-3.0-tiny-free |

Every agent has an explicit `fallback_models` chain (see [Fallback Policy](#fallback-policy)).

## Workflow

1. **Coordinate** — `matthew` defines architecture, routing, and handoffs.
2. **Build backend** — `alex` implements Python, APIs, data, and file operations.
3. **Build interface** — `sarah` implements TUI/frontend behavior and UX.
4. **Verify** — `david` writes and runs tests using a TDD workflow.
5. **Audit quality** — `elena` reviews code and security; `max` stabilizes automation.
6. **Document** — `chloe` audits state, plans, and the Obsidian vault, then reports drift.
7. **Deploy** — defined per-project (see `skills/deploy` when present).

## Conventions

- Never commit secrets. Keys live only in `~/.local/share/opencode/auth.json`.
- Never commit `knowledge/index.jsonl` or anything under `_logs/`.
- Consult `knowledge/` (via the `knowledge` reference) before planning or reviewing.
- Keep `PLAN.md` and `TASKS.json` at the project root of the target project.
- Commits are small and single-purpose; branch pattern `feature/{agent}-{task}`.

## Fallback Policy

Every agent carries an explicit ordered `fallback_models` chain in `opencode.json`.
The `@razroo/opencode-model-fallback` plugin (loaded via `.opencode/opencode.json`)
automatically switches to the next model in the chain when a request fails; opencode
itself only retries the same model, so this plugin is what makes failover real.

- **Chain (all 7 agents, in priority order):**
  1. `opencode/big-pickle` — Priority 1 fallback.
  2. `opencode/deepseek-v4-flash-free` — Priority 1 fallback (fast, reliable).
  3. `ollama/qwen2.5-coder:7b` — Priority 2 fallback (local, zero external cost).
- **Triggers** — the plugin falls back on: Rate Limit (HTTP 429), server errors
  (500/502/503/504/507), token limits, context exhaustion ("context length",
  "input is too long", "maximum context"), quota/usage-limit/credit-balance, and
  model-not-found.
- **Zero-wait failover** — `cooldown_seconds: 0` in
  `.opencode/opencode-model-fallback.jsonc` so a failed model is retried
  immediately on the next turn; no backoff delays, the workflow never halts.
- **Launcher note** — the worker passes `-m <primary>` which pins the session to
  the agent's primary model at launch; within that session, the plugin's fallback
  chain still applies on error. The chains also apply to any interactive or
  subagent use of these agents.

## Execution Environment (Windows)

This repo ships a human-facing 7-window launcher that runs the seven roles side
by side, each listening for tasks in its own inbox.

- **Launch** — run `launch_agents.bat` at the repo root, or in VS Code use the
  `Launch All Agents` terminal task (`.vscode/tasks.json`). Seven terminal
  windows open, titled `M1 - Matthew` … `M7 - Chloe`, positioned in
  a 4×2 grid.
- **Task inbox flow** — drop a single-line task into `_inbox/<agent>.task`
  (e.g. `_inbox/alex.task`). The agent's window polls the inbox, runs
  `opencode run --agent <name> -m <model> "<task>"`, appends the full output to
  `_logs/<agent>.log`, then moves the consumed task to `_inbox/done/`. Poll
  interval is 3s.
- **Window map** — `M1` matthew, `M2` alex, `M3` sarah,
  `M4` david, `M5` elena, `M6` max, `M7` chloe.
- **Event-driven handoff** — each role processes its inbox independently. To
  hand work to the next role, drop the next task into that role's inbox after
  the previous role logs completion. There is no shared queue; the operator (or
  a driving agent) sequences the drops.
- **Models** — the worker reads each agent's configured model from
  `opencode.json` and passes it explicitly (`-m`) so the role's own model is
  used. `-m` pins the session to the primary model at launch, but the
  model-fallback plugin still applies its chain on any failure within that
  session (see [Fallback Policy](#fallback-policy)). Model assignment is a
  hybrid of the three free models:
  - `opencode/ling-3.0-tiny-free` — ultra-fast routing/summarization: used for
    `compaction`, `elena`, and `chloe` (quick audit/documentation checks).
  - `opencode/deepseek-v4-flash-free` — heavy reasoning & coding:
    `matthew`, `alex`, `sarah`, and `max`.
  - `opencode/big-pickle` — QA and fallback reasoning: `david`.
  All three are free (no paid credits required). The MuleRouter provider block
  remains defined in `opencode.json` but is no longer used by default; its API
  key lives only in `~/.local/share/opencode/auth.json` (never committed).
- **Mode note** — all 7 agents are `mode: all`: they can be invoked standalone
  (`opencode run --agent X`) and still be used as subagents by other agents.
  The read-only annotations on `matthew`, `elena`, and `chloe` are permission-based
  (`edit: deny`) and are unaffected by the mode change.

## Memory & evolution

- Architecture decisions and lessons learned are appended to `knowledge/adr/` and
  `knowledge/lessons/`.
- After a milestone, run the retro command to summarize the session, prune
  stale memory, and update these conventions.

# AGENTS.md — MultiAgentCoding Control Plane

This repository is the **control plane** for a self-evolving multi-agent coding
system. It holds the MultiAgentCoding configuration, agent definitions, skills,
and memory used to drive software projects (typically under `projects/`).

## Roles

| Agent | Role | Model |
|---|---|---|
| `system-architect` | System architecture + design approval (read-only) | mulerouter/gpt-5.5 |
| `analyst` | Requirements analysis (read-only) | opencode/deepseek-v4-flash-free |
| `planner` | PLAN.md + TASKS.json (read-only) | mulerouter/qwen3.7-max |
| `backend-dev` | Backend implementation | mulerouter/gpt-5.5 |
| `frontend-dev` | Frontend implementation | mulerouter/gpt-5.4-mini |
| `tester` | Test authoring + execution | opencode/deepseek-v4-flash-free |
| `reviewer` | Code review, approve/reject (read-only) | mulerouter/qwen3-max |

Every agent has a fallback chain ending in `ollama/qwen2.5-coder:7b` (local).

Every agent has a fallback chain ending in `ollama/qwen2.5-coder:7b` (local).

## Workflow

1. **Analyze** — `analyst` turns the request into requirements.
2. **Design** — `system-architect` validates requirements and defines architecture.
3. **Plan** — `planner` writes `PLAN.md` + `TASKS.json`.
4. **Execute** — `backend-dev` / `frontend-dev` implement; `tester` writes/runs tests.
5. **Review** — `reviewer` reviews the diff; on approval it merges to `main`.
6. **Deploy** — defined per-project (see `skills/deploy` when present).

## Conventions

- Never commit secrets. Keys live only in `~/.local/share/opencode/auth.json`.
- Never commit `knowledge/index.jsonl` or anything under `_logs/`.
- Consult `knowledge/` (via the `knowledge` reference) before planning or reviewing.
- Keep `PLAN.md` and `TASKS.json` at the project root of the target project.
- Commits are small and single-purpose; branch pattern `feature/{agent}-{task}`.

## Execution Environment (Windows)

This repo ships a human-facing 7-window launcher that runs the seven roles side
by side, each listening for tasks in its own inbox.

- **Launch** — run `launch_agents.bat` at the repo root, or in VS Code use the
  `Launch All Agents` terminal task (`.vscode/tasks.json`). Seven terminal
  windows open, titled `M1 - System Architect` … `M7 - Reviewer`, positioned in
  a 4×2 grid.
- **Task inbox flow** — drop a single-line task into `_inbox/<agent>.task`
  (e.g. `_inbox/analyst.task`). The agent's window polls the inbox, runs
  `opencode run --agent <name> -m <model> "<task>"`, appends the full output to
  `_logs/<agent>.log`, then moves the consumed task to `_inbox/done/`. Poll
  interval is 3s.
- **Window map** — `M1` system-architect, `M2` analyst, `M3` planner,
  `M4` backend-dev, `M5` frontend-dev, `M6` tester, `M7` reviewer.
- **Event-driven handoff** — each role processes its inbox independently. To
  hand work to the next role, drop the next task into that role's inbox after
  the previous role logs completion. There is no shared queue; the operator (or
  a driving agent) sequences the drops.
- **Models** — the worker reads each agent's configured model from
  `opencode.json` and passes it explicitly (`-m`) so the role's own model is
  used (this pins the primary model and bypasses `fallback_models`, by design).
  Model assignment is hybrid by domain: heavy reasoning/coding agents use
  MuleRouter (`gpt-5.5`, `qwen3.7-max`, `gpt-5.4-mini`, `qwen3-max`), while
  light/fast agents use `opencode/deepseek-v4-flash-free`. MuleRouter is an
  OpenAI-compatible provider at `https://api.mulerouter.ai/vendors/openai/v1`;
  its API key lives only in `~/.local/share/opencode/auth.json` (never
  committed).
- **Mode note** — all 7 agents are `mode: all`: they can be invoked standalone
  (`opencode run --agent X`) and still be used as subagents by other agents.
  The read-only annotations on `system-architect`, `analyst`, `planner`, and
  `reviewer` are permission-based (`edit: deny`) and are unaffected by the mode
  change.

## Memory & evolution

- Architecture decisions and lessons learned are appended to `knowledge/adr/` and
  `knowledge/lessons/`.
- After a milestone, run the retro command to summarize the session, prune
  stale memory, and update these conventions.

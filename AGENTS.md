# AGENTS.md — MultiAgentCoding Control Plane

This repository is the **control plane** for a self-evolving multi-agent coding
system. It holds the opencode configuration, agent definitions, skills, and
memory used to drive software projects (typically under `projects/`).

## Roles

| Agent | Role | Model |
|---|---|---|
| `system-architect` | System architecture + design approval (read-only) | opencode/deepseek-v4-flash-free |
| `analyst` | Requirements analysis (read-only) | opencode/deepseek-v4-flash-free |
| `planner` | PLAN.md + TASKS.json (read-only) | groq/llama-3.3-70b-versatile |
| `backend-dev` | Backend implementation | groq/gpt-oss-120b |
| `frontend-dev` | Frontend implementation | groq/gpt-oss-120b |
| `tester` | Test authoring + execution | groq/llama-3.3-70b-versatile |
| `reviewer` | Code review, approve/reject (read-only) | opencode/deepseek-v4-flash-free |

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

## Memory & evolution

- Architecture decisions and lessons learned are appended to `knowledge/adr/` and
  `knowledge/lessons/`.
- After a milestone, run the retro command to summarize the session, prune
  stale memory, and update these conventions.

---
name: agent-team-sizing
description: Use when deciding how many agents should work on a task or project. Analyzes the prompt's scope, domains, and dependencies to recommend a team size (1, 2, 4, or more agents) and role assignment. Use when planning a new project or when the user asks how many agents are needed.
---

# Agent Team Sizing

## Purpose
Decide how many agents should work on a task, and which roles to assign,
based on the prompt's complexity and dependencies.

## When to Use

- When a new task or project arrives and you need to decide team size
- When the user asks "how many agents do I need?"
- Before planning and dispatching work to the swarm

## Step 1 — Analyze the task
Assess:
- **Scope** — how many files/areas will be touched?
- **Domains** — how many distinct domains (backend, frontend, tests, docs, infra)?
- **Dependencies** — can the work be split into independent parts?
- **Coordination** — how much communication between parts is required?

## Step 2: Decide team size

| Scenario | Signals | Team |
|----------|---------|------|
| Trivial | single file, <10 lines | 1 agent |
| Simple | 1-2 files, one domain | 1 agent |
| Moderate | 3-5 files, 1-2 domains | 2 agents |
| Complex | 5-10 files, 2-3 domains | 3-4 agents |
| Large | many files, 3+ domains, independent streams | 4+ agents |

## Step 3: Assign roles
Match agents to domains:
- Backend work → backend-dev
- Frontend work → frontend-dev
- Tests → tester
- Analysis/planning → planner, system-architect
- Review → reviewer

## Step 4: Check dependencies
- Only parallelize when tasks are truly independent
- If work is sequential, fewer agents is better
- More agents = more coordination overhead
- Never use more agents than there are independent work streams

## Rules of Thumb
- Start small: one agent for anything a single task can handle
- Add agents only when work is genuinely parallelizable
- Always include a tester for verification on non-trivial work
- When in doubt, prefer fewer agents and tighter scope
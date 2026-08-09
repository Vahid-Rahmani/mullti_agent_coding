---
name: prompt-engineering
description: Use when a user request is vague, ambiguous, or underspecified and needs to be refined into a clearer, more actionable prompt before planning or execution. Use keywords: prompt, refine, improve, clarify, rewrite, better prompt, make it clearer.
---

# Prompt Engineering (Master Agent)

## Purpose

Turn rough, vague, or incomplete user requests into precise, actionable
prompts that produce better planning and execution work.

## When to Use

- The user request is vague, ambiguous, or missing key constraints
- A single sentence could mean many different things
- The request lacks scope, constraints, or acceptance criteria
- Before starting a new feature or task that will be delegated to workers

## Process

### 1. Analyze the original prompt

Extract from the user's request:

| Element | Question to answer |
|---------|-------------------|
| **Goal** | What does the user actually want to achieve? |
| **Context** | What project, code, or constraints apply? |
| **Deliverables** | What must be produced? |
| **Constraints** | What must NOT be done? What tech/style is required? |

### 2. Identify gaps
Check for:
- **Ambiguity** — words that could mean multiple things
- **Missing context** — what does the agent need to know to act?
- **Missing constraints** — budget, time, tech stack, style
- **Missing acceptance criteria** — how do we know it's done?
- **Scope creep** — is the request too broad or too narrow?

### 3. Rewrite the prompt
Produce a structured prompt:

```markdown
## Goal
<what to achieve>

## Context
<relevant background>

## Scope
<what's in / what's out>

## Constraints
<must-haves and must-nots>

## Deliverables
<what to produce>

## Acceptance Criteria
<how to verify it's done>
```

### 4. Confirm with the user
If the rewrite changes meaning or adds constraints, present the refined prompt
and ask for confirmation via `question()` before proceeding.

## Rules

- Preserve the user's intent — never change what they asked for
- Ask when critical gaps are missing instead of guessing
- Keep the refined prompt concise and actionable
- Do not over-engineer: add structure only where it adds clarity
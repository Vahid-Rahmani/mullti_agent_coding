# Lesson: groq free-tier TPM cap vs opencode request size

## When
2026-08-07 — smoke testing the 7-window agent launcher.

## Symptom
`opencode run --agent X -m groq/...` failed for all groq models with
`Request too large for model ... on tokens per minute (TPM): Limit 8000, Requested ~40000`.

## Root cause
groq free-tier orgs cap at 8000 TPM. An `opencode run` for this control-plane repo
sends ~38–42k tokens per request (system prompt + opencode tool definitions +
AGENTS.md instructions). `--pure` (disable external plugins) only reduces this to
~38k. So groq models can never receive even one request from opencode on a free tier.

Also: `groq/gpt-oss-120b` is NOT a valid opencode model ID — the registry ID is
`groq/openai/gpt-oss-120b` (verify with `opencode models`).

## Decision
All 7 control-plane agents now use `opencode/deepseek-v4-flash-free` as primary
model. Groq models remain in `fallback_models` (they only trigger if the primary
provider is down — but note the worker pins `-m`, so fallbacks are bypassed in the
launcher by design).

## Takeaway
- Verify model IDs with `opencode models` before configuring agents.
- Free-tier TPM caps are a hard ceiling: check the request size (error message
  reports "Requested N") before assuming a provider will work with opencode's
  full context.
- `-m` in the launcher pins the primary model and intentionally bypasses
  `fallback_models`.

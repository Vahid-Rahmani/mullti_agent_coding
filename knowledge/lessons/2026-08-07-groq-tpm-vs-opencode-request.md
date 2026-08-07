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

## Resolution
All 7 control-plane agents now use a hybrid model assignment (primary models via
MuleRouter or opencode-deepseek):

| Agent | Primary model | Provider |
|---|---|---|
| system-architect | mulerouter/gpt-5.5 | MuleRouter |
| planner | mulerouter/qwen3.7-max | MuleRouter |
| backend-dev | mulerouter/gpt-5.5 | MuleRouter |
| frontend-dev | mulerouter/gpt-5.4-mini | MuleRouter |
| reviewer | mulerouter/qwen3-max | MuleRouter |
| analyst | opencode/deepseek-v4-flash-free | opencode |
| tester | opencode/deepseek-v4-flash-free | opencode |

- MuleRouter is an OpenAI-compatible provider: `https://api.mulerouter.ai/vendors/openai/v1`
  (the `/v1` alias 404s; use the `/vendors/openai/v1` path). Verified model IDs:
  `gpt-5.5`, `gpt-5.4-mini`, `qwen3-max`, `qwen3.7-max`.
- The MuleRouter key lives in `~/.local/share/opencode/auth.json` (never committed).
- groq models were dropped from `fallback_models` (they cannot run on the free tier);
  fallbacks are now `opencode/deepseek-v4-flash-free` → `ollama/qwen2.5-coder:7b`.
- `opencode/big-pickle` is opencode-hosted, NOT available on MuleRouter.

## Takeaway
- Verify model IDs with `opencode models` before configuring agents.
- Free-tier TPM caps are a hard ceiling: check the request size (error message
  reports "Requested N") before assuming a provider will work with opencode's
  full context.
- `-m` in the launcher pins the primary model and intentionally bypasses
  `fallback_models`.
- MuleRouter: the OpenAI-compatible base path is `/vendors/openai/v1`, not `/v1`.

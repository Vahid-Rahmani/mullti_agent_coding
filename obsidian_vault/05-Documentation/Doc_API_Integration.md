---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Documentation_Home, Component_RunHub, Component_AgentSpecs, System_Architecture]
---

# Doc_API_Integration

**Type:** documentation · **Status:** active (existing — pointer card) · **Owner:** all

## Category

API/Integration

## Purpose

Documents the **real** integration surfaces of the control plane. Nothing is
claimed that does not exist: there is no web API, no REST endpoint, and no
Obsidian bridge yet.

## Verified Integration Points

- **Dispatch command:** `opencode run --agent <a> --auto -m <model> "<prompt>"`
  (built by [[Component_RunHub]] and the inbox workers).
- **Model providers** (in `opencode.json`): `ollama` (local,
  `qwen2.5-coder:7b`) and `mulerouter` (defined; not used by default).
- **Fallback chain** (all agents):
  `[opencode/big-pickle, opencode/deepseek-v4-flash-free, ollama/qwen2.5-coder:7b]`
  via the `@razroo/opencode-model-fallback` plugin.
- **Knowledge reference:** `./knowledge` is wired as an opencode `references` path.

## Repository References

| Doc | Path | Status |
|---|---|---|
| opencode config | `opencode.json` | existing |
| Fallback plugin config | `.opencode/opencode-model-fallback.jsonc` | existing |

## Planned (not claimed)

- Vault bridge (`scripts/vault_bridge.py`) — **planned**.
- `/vault` terminal command — **planned**.

## Links

- ↑ Parent: [[Documentation_Home]]
- ↔ Related: [[Component_RunHub]], [[Component_AgentSpecs]], [[System_Architecture]]

---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-17
related: [Documentation_Home, Component_RunHub, Component_AgentSpecs, Component_Orchestrator, Component_VaultBridge, Component_ContextResolver, System_Architecture]
---

# Doc_API_Integration

**Type:** documentation · **Status:** active (existing — pointer card) · **Owner:** all

## Category

API/Integration

## Purpose

Documents the **real** integration surfaces of the control plane: OpenCode
dispatch, the local Agent Dashboard API, and the implemented Vault stack.

## Verified Integration Points

- **Dispatch command:** `opencode run --agent <a> --auto -m <model> "<prompt>"`
  (built by [[Component_RunHub]] and the inbox workers).
- **Model providers** (in `opencode.json`): `ollama` (local,
  `qwen2.5-coder:7b`) and `mulerouter` (defined; not used by default).
- **Fallback chain** (all agents):
  `[opencode/big-pickle, opencode/deepseek-v4-flash-free, ollama/qwen2.5-coder:7b]`
  via the `@razroo/opencode-model-fallback` plugin.
- **Knowledge reference:** `./knowledge` is wired as an opencode `references` path.
- **Vault task execution:** [[Component_Orchestrator]] reads and executes
  lifecycle-controlled task nodes with bounded [[Component_ContextResolver]]
  context and explicit authorization.
- **Vault I/O:** [[Component_VaultBridge]] provides scoped reads, atomic managed
  writes, backups, relationship resolution, and change logs.
- **Local Dashboard API:** `scripts/web_ui/routes.py` exposes local REST/SSE
  endpoints over the existing RunHub, Orchestrator, Vault, and workflow layers.

## Repository References

| Doc | Path | Status |
|---|---|---|
| opencode config | `opencode.json` | existing |
| Fallback plugin config | `.opencode/opencode-model-fallback.jsonc` | existing |
| Vault bridge | `scripts/core/vault_bridge.py` | existing |
| Task orchestrator | `scripts/core/orchestrator.py` | existing |
| Context resolver | `scripts/core/context_resolver.py` | existing |
| Dashboard routes | `scripts/web_ui/routes.py` | existing |

## Planned (not claimed)

- `/vault` terminal command — **planned**.

## Links

- ↑ Parent: [[Documentation_Home]]
- ↔ Related: [[Component_RunHub]], [[Component_AgentSpecs]], [[Component_Orchestrator]], [[Component_VaultBridge]], [[Component_ContextResolver]], [[System_Architecture]]

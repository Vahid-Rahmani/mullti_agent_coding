---
type: documentation
status: active
owner: all
created: 2026-08-11
updated: 2026-08-11
related: [Documentation_Home, Doc_Operations, Component_Launchers]
---

# Doc_Troubleshooting

**Type:** documentation · **Status:** active (existing — pointer card) · **Owner:** all

## Category

Troubleshooting

## Purpose

Known issues and fixes (verified from `README.md` / `AGENTS.md`). Full text
lives in the repo; this card links to it and summarizes.

## Known Issues

| Issue | Fix |
|---|---|
| `self signed certificate in certificate chain` (opencode/Node rejecting self-signed/intercepting cert) | Preferred: set `NODE_EXTRA_CA_CERTS` to the CA bundle; opt-in bypass: `ZOVA_ALLOW_INSECURE_TLS=1` before launch (off by default) |

## Repository References

| Doc | Path | Status |
|---|---|---|
| README troubleshooting | `README.md` → Troubleshooting | existing |
| AGENTS.md TLS note | `AGENTS.md` → Execution Environment | existing |

## Links

- ↑ Parent: [[Documentation_Home]]
- ↔ Related: [[Doc_Operations]], [[Component_Launchers]]

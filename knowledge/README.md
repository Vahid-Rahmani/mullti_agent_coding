# knowledge/

Project memory for the control plane. Consult this before planning or
reviewing (wired into OpenCode via the `references.knowledge` config key in
`opencode.json`).

- `adr/` — architecture decision records (one file per decision; empty until
  the first decision is recorded).
- `lessons/` — lessons learned and recurring failure patterns.
- `sources/` — the external knowledge / reference layer: one record per
  upstream repository researched for MultiAgentCoding (license, purpose,
  useful concepts, and the integration decision). These are research/reference
  sources, not runtime dependencies. See `sources/README.md` for the license
  matrix and the source → prompt/workflow reference map.
- `metrics.jsonl` — per-session metrics (tokens, success, interventions).
- `fine_tune_dataset.jsonl` — reserved for fine-tuning data (currently empty).

The OpenCode search index (`knowledge/index.jsonl`) is a generated runtime
artifact and is **never committed** (see `.gitignore`).

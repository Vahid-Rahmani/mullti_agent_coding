# knowledge/

Project memory for the control plane. Consult this before planning or
reviewing (wired into OpenCode via the `references.knowledge` config key in
`opencode.json`).

- `adr/` — architecture decision records (one file per decision; empty until
  the first decision is recorded).
- `lessons/` — lessons learned and recurring failure patterns.
- `metrics.jsonl` — per-session metrics (tokens, success, interventions).
- `fine_tune_dataset.jsonl` — reserved for fine-tuning data (currently empty).

The OpenCode search index (`knowledge/index.jsonl`) is a generated runtime
artifact and is **never committed** (see `.gitignore`).

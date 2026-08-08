# PLAN.md — UI/UX Redesign & Layout Overhaul (Web Workspace)

## Objective
Redesign the AI Agent Workspace **web UI** (`scripts/web_app.py`) to deliver three
user-visible improvements:

1. **Font Scaling** — increase all base typography, log text, and UI font sizes
   significantly across the web application to ensure high readability and
   eliminate tiny fonts.
2. **Single Window Streamlined Layout** — remove redundant empty spaces and
   compact the layout into a clean, unified single-window workspace where the
   **Terminal logs + main chat box are seamlessly integrated** (no empty dead
   zones between them).
3. **Modern Theme Polish** — refine the dark theme aesthetics to look sleek,
   modern, and professional, ensuring full responsiveness and optimal spacing.

## Scope
**In scope**
- `scripts/web_app.py` — the `PAGE_HTML` UI constant (markup, Tailwind classes,
  `<style>` block, and the JS that renders chat / console / settings).
- `test/tests/test_web_app.py` — UI-marker assertions that must be updated to
  match the new markup (all other test classes stay green unchanged).

**Out of scope**
- Backend/API semantics: every `/api/*` endpoint keeps its current contract.
- `scripts/unified_app.py` (desktop GUI) — unchanged.
- `scripts/intent_router.py`, `scripts/self_evolve.py`, `scripts/supervisor.py`.
- `opencode.json`, provider/auth handling, `_logs/`, `knowledge/`.

## Current State Baseline
- Single-file FastAPI + Tailwind-CDN + vanilla JS. UI is `PAGE_HTML`
  (web_app.py lines ~1166–2096). Layout: top bar → flex row
  [icon sidebar `w-14`] [center workplane: tab header + `#chat` +
  quick-actions + input] [right Terminal Logs rail `w-96`].
- **Tiny fonts everywhere**: terminal `text-[11px]`, thoughts `text-[11px]`,
  response `text-xs`, badges `text-[10px]`, source chips `text-[9px]`,
  `pre.codeblock` 12px, `text-xs` selects/buttons/inputs.
- Dark palette: `bg #0B0E14 / panel #0F172A / panel2 #1E293B / edge #293548 /
  accent #38BDF8 / lime #A3E635 / txt #E2E8F0 / muted #94A3B8 / danger #F87171`.
- **`test/tests/*.py` are tracked in git but deleted on disk** — restore them
  first so the suite can run as a baseline.

## Non-Goals
- No new/removed API endpoints; no provider CRUD changes; no run-flow changes.
- No changes to the desktop GUI or the routing/self-evolve backends.
- No persistence changes; this is a presentation + markup refactor only.

## Epics
1. **E1 — Typography Scaling**: root font-size bump plus elimination of all
   sub-12px text (terminal logs, code blocks, badges, chips, labels, controls).
2. **E2 — Single-Window Layout**: integrate Terminal Logs into the main
   workplane as a bottom console panel; compact spacing; remove dead zones.
3. **E3 — Theme Polish + Responsiveness**: refined dark-theme aesthetics,
   hover/focus states, consistent borders/radius, responsive behavior.
4. **E4 — Tests + Verification**: restore suite, update UI markers, full-suite
   run + headless smoke test.

## Phases
- **Phase A — Foundation**: restore the deleted test suite and confirm a green
  baseline (T1).
- **Phase B — Typography**: root/base scaling (T2) → terminal/code/response
  (T3) → micro-labels/badges/chips/controls (T4).
- **Phase C — Layout**: unified single-window console (T5) → compact spacing
  (T6).
- **Phase D — Theme**: dark-theme polish (T7) → responsiveness (T8).
- **Phase E — Verify**: UI-marker test updates (T9) → E2E verification (T10).

All frontend tasks edit the same single file (`PAGE_HTML` in `web_app.py`), so
they are **strictly ordered** (no parallel edits to that file).

## Definition of Done
- No text smaller than 12px anywhere in the UI (terminal logs ≥ 13px).
- Terminal Logs + chat form one integrated workspace; no dead zones at widths
  ≥ 1280px.
- Dark theme looks polished; app fully usable from ~360px to ~1920px width.
- Full suite green: `python -m unittest discover -s test/tests -v` (exit 0).
- Headless smoke: `python scripts/web_app.py --no-browser --port 8512` serves
  `/` (200) with expected markers; `/api/catalog`, `/api/status`, `/api/route`
  respond correctly; server stopped afterwards.
- `git status` shows no test deletions, no stray files, no secrets.

## Verification Commands
- `python -m unittest discover -s test/tests -v`
- `python scripts/web_app.py --no-browser --port 8512` then
  `Invoke-WebRequest http://127.0.0.1:8512/` (200 + markers)
- `git status --short` clean of test-dir noise.

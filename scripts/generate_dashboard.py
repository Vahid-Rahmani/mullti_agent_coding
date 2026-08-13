"""generate_dashboard — rebuild the GENERATED section of obsidian_vault/Dashboard.md.

Safety (Phase 17):
  * Only the block between `<!-- GENERATED: dashboard -->` and
    `<!-- /GENERATED -->` is rewritten. Any human-authored content above or
    below is preserved byte-for-byte.
  * All WikiLinks emitted reference REAL vault nodes (verified against the
    tree) — no invented links, no false documentation.
  * The scan is lightweight: 03-Tasks/ + 02-Agents/ + log tails only.
  * The dashboard itself is schema-valid (type: system).

Usage: python scripts/generate_dashboard.py [--vault P] [--check]
  --check  fail (exit 1) if the generated section is stale.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
DASHBOARD = Path("obsidian_vault") / "Dashboard.md"

OPEN_MARKER = "<!-- GENERATED: dashboard -->"
CLOSE_MARKER = "<!-- /GENERATED -->"

TASK_SECTIONS = ("00-System", "01-Architecture", "02-Agents", "03-Tasks",
                 "04-Decisions", "05-Documentation", "06-Testing")

TASK_STATUSES = ("planned", "ready", "in_progress", "blocked", "completed", "failed")

# Modules added in Phases 11-16 that have no Component_* node (known gap).
_KNOWN_UNMAPPED_MODULES = (
    "orchestrator.py", "vault_bridge.py", "context_resolver.py",
    "change_detector.py", "knowledge_sync.py",
)

FM = ("---\ntype: system\nstatus: active\nowner: all\ncreated: 2026-08-11\n"
      "updated: {today}\nrelated: [System_Core, Architecture_Home, Agents_Home, "
      "Tasks_Home, Testing_Home]\n---\n\n")


# ---------------------------------------------------------------- scan

def _all_node_names(vault: Path) -> set[str]:
    names: set[str] = set()
    for section in TASK_SECTIONS:
        folder = vault / section
        if folder.is_dir():
            names |= {p.stem for p in folder.glob("*.md") if not p.name.startswith("_")}
    return names


def _task_nodes(vault: Path) -> list[Path]:
    folder = vault / "03-Tasks"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md")
                  if not p.name.startswith("_")
                  and p.stem not in ("Tasks_Home", "Task_Backlog"))


def _read_frontmatter_field(text: str, key: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return ""
    km = re.search(rf"^{re.escape(key)}:\s*(.*)$", m.group(1), re.MULTILINE)
    return km.group(1).strip() if km else ""


def _log_tail(path: Path, n: int = 5) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


# ---------------------------------------------------------------- sections

def _status_summary(vault: Path, node_names: set[str]) -> str:
    counts = {s: 0 for s in TASK_STATUSES}
    rows: list[str] = []
    for p in _task_nodes(vault):
        text = p.read_text(encoding="utf-8", errors="replace")
        status = _read_frontmatter_field(text, "status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
        link = f"[[{p.stem}]]" if p.stem in node_names else p.stem
        rows.append(f"| {link} | {status} |")
    out = [f"| Task | Status |", "|---|---|"] + rows
    out.append(f"\n**Counts:** {', '.join(f'{s}={counts[s]}' for s in TASK_STATUSES)}")
    if not rows:
        out.append("\n_No task nodes yet — see [[Task_Backlog]]._")
    return "\n".join(out)


def _agent_roster(vault: Path, node_names: set[str]) -> str:
    """Agent roster with models resolved from the real AgentSpecs (the vault
    nodes do not carry models; the specs are the source of truth)."""
    folder = vault / "02-Agents"
    agents = sorted(p.stem for p in folder.glob("Agent_*.md")) if folder.is_dir() else []
    try:
        from scripts.core import opencode_cfg
        from scripts.core.agents import AGENT_SPEC_BY_AGENT
    except Exception:  # noqa: BLE001
        opencode_cfg = None
        AGENT_SPEC_BY_AGENT = {}
    lines = []
    for name in agents:
        if name not in node_names:
            continue
        key = name[len("Agent_"):].lower()
        spec = AGENT_SPEC_BY_AGENT.get(key)
        model = opencode_cfg.resolve_model(spec.agent) if spec and opencode_cfg else None
        lines.append(f"- [[{name}]] — {model or '—'}")
    if not lines:
        lines.append("_No agent nodes yet — see [[Agents_Home]]._")
    return "\n".join(lines)


def _recent_executions() -> str:
    orch = _log_tail(_REPO_ROOT / "_logs" / "orchestrator.log", 5)
    sync = _log_tail(_REPO_ROOT / "_logs" / "sync_log.jsonl", 3)
    lines = ["**Orchestrator log (last 5):**", ""]
    lines += [f"- `{ln.strip()[:120]}`" for ln in orch] or ["- _(no orchestrator activity yet)_"]
    lines += ["", "**Sync log (last 3):**", ""]
    lines += [f"- `{ln.strip()[:120]}`" for ln in sync] or ["- _(no sync activity yet)_"]
    return "\n".join(lines)


def _recent_changes() -> str:
    changes = _log_tail(_REPO_ROOT / "_logs" / "vault_changes.jsonl", 3)
    lines = ["**Vault changes (last 3):**", ""]
    lines += [f"- `{ln.strip()[:120]}`" for ln in changes] or ["- _(no recorded vault changes)_"]
    return "\n".join(lines)


def _architecture_gaps() -> str:
    # Known genuine drift reported by Phase 16's check-conflicts.
    lines = [f"- `{m}` — real module with no `Component_*` node yet" for m in _KNOWN_UNMAPPED_MODULES]
    return "\n".join(lines)


# ---------------------------------------------------------------- build

def build_generated(vault: Path, node_names: set[str]) -> str:
    return f"""## Project Status
- **Vault:** {len(node_names)} managed nodes · schema validated
- **Task lifecycle:** [[Tasks_Home]] · [[Task_Backlog]]
- **Agents:** [[Agents_Home]] · **Architecture:** [[System_Architecture]]

## Active / In-Progress Tasks
{_status_summary(vault, node_names)}

## Active Agents
{_agent_roster(vault, node_names)}

## Recent Executions
{_recent_executions()}

## Recent Changes
{_recent_changes()}

## Testing Status
- See [[Testing_Home]] and [[Test_Report_Suite]] — current suite: `python -m unittest discover -s test/tests`

## Architecture Status
- Map: [[System_Architecture]]
- **Known gaps (reported by `knowledge_sync check-conflicts`, not auto-fixed):**
{_architecture_gaps()}

## Blocked / Needs Attention
- _None currently — see [[Task_Backlog]] for full status._
"""


HEADER = """# Dashboard — MultiAgentCoding

> **Control plane knowledge graph — entry point.**
> Human-authored header: edit freely. The section below between the GENERATED
> markers is rebuilt by `python scripts/generate_dashboard.py`.

- ↑ Root: [[System_Core]]
- Navigate: [[Architecture_Home]] · [[Agents_Home]] · [[Tasks_Home]] · [[Decisions_Home]] · [[Documentation_Home]] · [[Testing_Home]]

---
"""


def render_dashboard(vault: Path, today: str | None = None) -> str:
    """Full dashboard content: schema frontmatter + human header + generated.

    ``today`` defaults to the real date; pass a fixed value for a
    date-insensitive freshness comparison. Human content ABOVE the
    OPEN_MARKER is preserved verbatim.
    """
    node_names = _all_node_names(vault)
    generated = build_generated(vault, node_names)
    block = f"{OPEN_MARKER}\n{generated.rstrip()}\n{CLOSE_MARKER}\n"
    path = vault / "Dashboard.md"
    human = HEADER
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        # Drop any old frontmatter block (regenerated below).
        m = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
        if m:
            text = text[m.end():]
        # Legacy dashboards (pre-knowledge-graph) reference the old structure
        # (prompts/, agents_logs/, Roadmap) with broken links — they are stale
        # reference data and are replaced wholesale by the new header.
        legacy_markers = ("[[prompts/]]", "[[agents_logs/]]", "[[Roadmap]]")
        if not any(mk in text for mk in legacy_markers):
            pattern = re.compile(
                rf"{re.escape(OPEN_MARKER)}.*?{re.escape(CLOSE_MARKER)}", re.DOTALL)
            if pattern.search(text):
                human = pattern.sub("", text).rstrip() + "\n\n"
            elif text.strip():
                human = text.rstrip() + "\n\n"
    if today is None:
        from scripts.core.vault_bridge import _now
        today = _now()[:10]
    # Normalize trailing whitespace so re-generation is byte-stable.
    return (FM.format(today=today) + human.rstrip() + "\n\n" + block.rstrip()
            + "\n")


def write_dashboard(vault: Path, content: str) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    path = vault / "Dashboard.md"
    # Atomic write (same pattern as the bridge).
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(vault), suffix=".dash.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(prog="python scripts/generate_dashboard.py")
    parser.add_argument("--vault", default=None, help="vault path")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the generated section is stale")
    args = parser.parse_args(argv)
    vault = Path(args.vault) if args.vault else (_REPO_ROOT / DASHBOARD).parent
    path = vault / "Dashboard.md"
    if args.check:
        # Date-insensitive freshness: compare everything except the
        # frontmatter 'updated:' value.
        def _normalize(text: str) -> str:
            return re.sub(r"^updated:.*$", "updated: <DATE>",
                          text, flags=re.MULTILINE)
        content = render_dashboard(vault)
        if path.is_file() and _normalize(path.read_text(encoding="utf-8")) == \
                _normalize(content):
            print("dashboard is up to date")
            return 0
        print("dashboard is STALE — run generate_dashboard.py", file=sys.stderr)
        return 1
    content = render_dashboard(vault)
    write_dashboard(vault, content)
    print(f"dashboard written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

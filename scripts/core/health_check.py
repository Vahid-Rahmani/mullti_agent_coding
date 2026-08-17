"""HealthCheck — comprehensive validation of the Obsidian knowledge graph.

Detection-only (Phase 18): every check is read-only. Nothing is repaired —
destructive or ambiguous problems are REPORTED with a recommended manual fix.
The report is printed and appended to _logs/health_report.jsonl.

Checks:
  errors   broken WikiLinks, missing required frontmatter, invalid task
           statuses, unresolvable agent references, unreachable hubs
  warnings orphan nodes, circular dependencies, duplicate node names,
           cross-section inconsistency, docs-vs-code drift (Phase 16),
           legacy vault files
  healthy  every node that passes all applicable checks

CLI: python -m scripts.core.health_check [--vault P] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
HEALTH_LOG = Path("_logs") / "health_report.jsonl"

SECTIONS = ("00-System", "01-Architecture", "02-Agents", "03-Tasks",
            "04-Decisions", "05-Documentation", "06-Testing")
LEGACY_FILES = ("Dashboard.md", "Roadmap.md", "prompts/", "agents_logs/")

REQUIRED_FIELDS = ("type", "status", "owner", "created", "updated")
TASK_STATUSES = {"planned", "ready", "in_progress", "blocked", "completed", "failed"}
VALID_TYPES = {"system", "architecture", "agent", "task", "decision", "documentation", "test"}
ROOT_NODES = {"System_Core"} | {f"{s.split('-', 1)[1]}_Home" for s in SECTIONS}

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
LINK_RE = re.compile(r"\[\[([^|\]]+)(?:\[[^\]]*\])?(?:\|[^\]]+)?\]\]")
KEY_RE = re.compile(r"^(\w+):\s*(.*)$")


@dataclass
class Node:
    path: Path          # absolute
    rel: str            # vault-relative, forward slashes
    name: str           # stem
    section: str
    text: str
    fields: dict[str, str]
    body: str
    links: list[str]    # outgoing WikiLink targets
    is_legacy: bool = False


@dataclass
class Issue:
    severity: str       # "error" | "warning"
    check: str
    message: str
    fix: str


@dataclass
class HealthReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    healthy: list[str] = field(default_factory=list)
    unhealthy: set[str] = field(default_factory=set)
    checks_run: int = 0

    def add(self, issue: Issue, node: str | None = None) -> None:
        (self.errors if issue.severity == "error" else self.warnings).append(issue)
        if node:
            self.unhealthy.add(node)

    def to_dict(self) -> dict:
        return {
            "errors": [i.__dict__ for i in self.errors],
            "warnings": [i.__dict__ for i in self.warnings],
            "healthy": self.healthy,
            "checks_run": self.checks_run,
        }


# ---------------------------------------------------------------- scan

def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract flat ``key: value`` pairs into a dict (tolerant, detection-only).

    Intentionally DIFFERENT from the canonical parser
    (``scripts.core.vault_bridge.parse_frontmatter``): that parser is strict —
    it returns an ``(fields, error)`` tuple and treats a missing frontmatter
    block or an unparseable line as an error. HealthCheck is a read-only
    *detector* that must survive malformed nodes and still report on them, so
    this helper stays permissive: a missing block yields ``{}``, and lines
    without a ``key: value`` shape are skipped rather than fatal. Downstream
    checks then report the *effect* (missing required fields) instead of the
    parse error, which is the intended detection-only contract.
    """
    m = FM_RE.match(text)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        km = KEY_RE.match(line.strip())
        if km:
            fields[km.group(1)] = km.group(2).strip()
    return fields


def _is_legacy(rel: str) -> bool:
    return rel in {"Dashboard.md", "Roadmap.md"} or rel.startswith(
        ("prompts/", "agents_logs/"),
    )


def scan_vault(vault: Path) -> list[Node]:
    nodes: list[Node] = []
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("_"))
        for fname in sorted(filenames):
            if not fname.endswith(".md"):
                continue
            full = Path(dirpath) / fname
            rel = full.relative_to(vault)
            rel_str = str(rel).replace(os.sep, "/")
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fields = _parse_frontmatter(text)
            m = FM_RE.match(text)
            body = text[m.end():] if m else text
            # Links are collected from prose only — code fences, inline code,
            # and template placeholders (``[[WikiLinks]]``, ``[[Node_Name]]``)
            # are documentation examples, not graph links (same convention as
            # the vault validator).
            prose = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
            prose = re.sub(r"`[^`]*`", "", prose)
            links = []
            for lm in LINK_RE.finditer(prose):
                target = lm.group(1).strip()
                if target and target not in links:
                    links.append(target)
            section = rel.parts[0] if len(rel.parts) > 1 else "(root)"
            nodes.append(Node(path=full, rel=rel_str, name=full.stem, section=section,
                              text=text, fields=fields, body=body, links=links,
                              is_legacy=_is_legacy(rel_str)))
    return nodes


# ---------------------------------------------------------------- checks

def check_frontmatter(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    for n in nodes:
        if n.is_legacy or n.name.startswith("_"):
            continue  # templates are exempt: placeholders, not managed nodes
        missing = [k for k in REQUIRED_FIELDS if k not in n.fields]
        if missing:
            report.add(Issue("error", "frontmatter",
                             f"{n.rel}: missing required field(s): {', '.join(missing)}",
                             "add the missing frontmatter keys per Node_Schema_Reference"),
                        node=n.name)
        ntype = n.fields.get("type", "")
        if ntype and ntype not in VALID_TYPES:
            report.add(Issue("error", "frontmatter",
                             f"{n.rel}: invalid type {ntype!r}",
                             "set type to one of: " + ", ".join(sorted(VALID_TYPES))),
                        node=n.name)


def check_broken_links(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    names = {n.name for n in nodes}
    for n in nodes:
        if n.is_legacy or n.name.startswith("_"):
            continue  # templates intentionally contain placeholder examples
        for target in n.links:
            # Skip explicit directory links (e.g. [[prompts/]]) in legacy files.
            if target.endswith("/"):
                continue
            # Skip template placeholder targets ([[Task_<Short_Name>]]).
            if "<" in target or ">" in target:
                continue
            if target not in names:
                report.add(Issue(
                    "error", "broken-link",
                    f"{n.rel}: [[{target}]] has no matching node",
                    f"create {target}.md or fix the link in {n.rel}"),
                    node=n.name)


def check_task_statuses(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    for n in nodes:
        if n.section != "03-Tasks" or n.is_legacy:
            continue
        if n.name in ("Tasks_Home", "Task_Backlog"):
            continue  # hubs use the shared schema, not task lifecycle
        status = n.fields.get("status", "")
        if status and status not in TASK_STATUSES:
            report.add(Issue(
                "error", "task-status",
                f"{n.rel}: invalid task status {status!r}",
                "set status to one of: " + ", ".join(sorted(TASK_STATUSES))),
                node=n.name)


def check_agent_refs(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    agent_names = {n.name for n in nodes if n.section == "02-Agents"}
    for n in nodes:
        if n.section != "03-Tasks" or n.is_legacy or n.name in ("Tasks_Home", "Task_Backlog"):
            continue
        assigned = n.fields.get("assigned_agent", "")
        if assigned and assigned not in agent_names:
            report.add(Issue(
                "error", "agent-ref",
                f"{n.rel}: assigned_agent {assigned!r} has no Agent_* node",
                "create the agent node or fix assigned_agent"),
                node=n.name)


def check_orphans(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    incoming: dict[str, int] = defaultdict(int)
    names = {n.name for n in nodes}
    for n in nodes:
        for target in n.links:
            if target in names:
                incoming[target] += 1
    managed = [n for n in nodes if not n.is_legacy]
    for n in managed:
        if n.name in ROOT_NODES:
            continue  # roots are linked from System_Core by definition
        if incoming[n.name] == 0:
            report.add(Issue(
                "warning", "orphan",
                f"{n.rel}: no node links to it (and it is not a root)",
                f"add a parent/related link to {n.name} from its section hub or System_Core"),
                node=n.name)


def check_duplicates(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    by_stem: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        if not n.is_legacy:
            by_stem[n.name].append(n.rel)
    for stem, rels in by_stem.items():
        if len(rels) > 1:
            report.add(Issue(
                "warning", "duplicate",
                f"node name {stem!r} exists in multiple locations: {', '.join(rels)}",
                "rename one of the duplicates (WikiLinks resolve by unique name)"))


def check_cycles(nodes: list[Node], report: HealthReport) -> None:
    """DFS cycle detection over the whole link graph.

    Mutual 'related' links (A->B and B->A) are INTENTIONAL in a knowledge
    graph (bidirectional references) — only cycles of length >= 3 through
    DISTINCT nodes are reported. Hubs are excluded as navigation roots.
    """
    report.checks_run += 1
    names = {n.name for n in nodes}
    graph = {n.name: [t for t in n.links if t in names and not t.endswith("_Home")]
             for n in nodes}

    # Remove mutual 2-cycles (A<->B) from consideration: they are benign
    # bidirectional references, not dependency cycles.
    mutual: set[tuple[str, str]] = set()
    for a, nbrs in graph.items():
        for b in nbrs:
            if a in graph.get(b, []):
                mutual.add(tuple(sorted((a, b))))
    for a, b in mutual:
        graph[a] = [x for x in graph[a] if x != b]
        graph[b] = [x for x in graph[b] if x != a]
    state: dict[str, int] = {}  # 0=unvisited 1=on-path 2=done
    cycles: list[str] = []

    def dfs(name: str, path: list[str]) -> None:
        state[name] = 1
        path.append(name)
        for nxt in sorted(graph.get(name, [])):
            if state.get(nxt, 0) == 1:
                start = path.index(nxt) if nxt in path else 0
                cycles.append(" -> ".join(path[start:] + [nxt]))
            elif state.get(nxt, 0) == 0:
                dfs(nxt, path)
        path.pop()
        state[name] = 2

    for name in sorted(graph):
        if state.get(name, 0) == 0:
            dfs(name, [])
    for cycle in cycles[:10]:
        report.add(Issue("warning", "cycle",
                         f"circular link chain: {cycle}",
                         "break the cycle by removing one of the links"))


def check_reachability(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    names = {n.name for n in nodes}
    graph = {n.name: [t for t in n.links if t in names] for n in nodes}
    if "System_Core" not in graph:
        report.add(Issue("error", "reachability",
                         "System_Core node is missing from the graph",
                         "create 00-System/System_Core.md"))
        return
    seen: set[str] = set()
    queue: deque[str] = deque(["System_Core"])
    while queue:
        cur = queue.popleft()
        for nxt in graph.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    seen.add("System_Core")
    for n in nodes:
        if n.is_legacy:
            continue
        if n.name in ROOT_NODES and n.name not in seen:
            report.add(Issue("error", "reachability",
                             f"{n.rel}: critical node not reachable from System_Core",
                             "link it from System_Core's Main Sections"),
                        node=n.name)
        elif n.name not in seen:
            report.add(Issue("warning", "reachability",
                             f"{n.rel}: not reachable from System_Core",
                             f"link {n.name} from a reachable node"),
                        node=n.name)


def check_consistency(nodes: list[Node], report: HealthReport) -> None:
    """Cross-section consistency: hubs list their children."""
    report.checks_run += 1
    by_name = {n.name: n for n in nodes}
    hub_children = {
        "Agents_Home": ("02-Agents", "Agent_"),
        "Architecture_Home": ("01-Architecture", ""),
        "Testing_Home": ("06-Testing", ""),
        "Documentation_Home": ("05-Documentation", ""),
        "Decisions_Home": ("04-Decisions", ""),
        "Tasks_Home": ("03-Tasks", ""),
    }
    exempt = {"Task_Backlog"}
    for hub, (section, prefix) in hub_children.items():
        hub_node = by_name.get(hub)
        if hub_node is None:
            continue
        listed = set(hub_node.links)
        for n in nodes:
            if n.section != section or n.name == hub or n.is_legacy:
                continue
            if n.name in exempt:
                continue
            if prefix and not n.name.startswith(prefix):
                continue
            if n.name not in listed:
                report.add(Issue(
                    "warning", "consistency",
                    f"{n.rel}: not linked from [[{hub}]]",
                    f"add [[{n.name}]] to {hub}'s children list"))


def check_conflicts(vault: Path, report: HealthReport) -> None:
    report.checks_run += 1
    try:
        from scripts.core.knowledge_sync import check_conflicts as ks_check
        for conflict in ks_check(vault):
            report.add(Issue("warning", "docs-code",
                             conflict,
                             "update the architecture map (System_Architecture or a Component_* node) "
                             "to reflect the real codebase"))
    except Exception as exc:  # noqa: BLE001
        report.add(Issue("warning", "docs-code",
                         f"conflict check failed: {exc}", "investigate"))


def check_legacy(nodes: list[Node], report: HealthReport) -> None:
    report.checks_run += 1
    legacy = [n for n in nodes if n.is_legacy]
    if legacy:
        report.add(Issue(
            "warning", "legacy",
            f"legacy vault files predate the knowledge graph and are exempt from checks: "
            f"{', '.join(n.rel for n in legacy[:6])}",
            "migrate or remove them when convenient"))


# ---------------------------------------------------------------- report

def run_health(vault: Path) -> HealthReport:
    nodes = scan_vault(vault)
    report = HealthReport()
    check_frontmatter(nodes, report)
    check_broken_links(nodes, report)
    check_task_statuses(nodes, report)
    check_agent_refs(nodes, report)
    check_orphans(nodes, report)
    check_duplicates(nodes, report)
    check_cycles(nodes, report)
    check_reachability(nodes, report)
    check_consistency(nodes, report)
    check_conflicts(vault, report)
    check_legacy(nodes, report)
    report.healthy = sorted(
        n.name for n in nodes if not n.is_legacy and n.name not in report.unhealthy)
    return report


def log_report(report: HealthReport) -> None:
    from scripts.core.vault_bridge import _now
    record = {"ts": _now(), **report.to_dict()}
    try:
        path = _REPO_ROOT / HEALTH_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError):
        pass


def print_report(report: HealthReport, json_out: bool = False) -> None:
    if json_out:
        print(json.dumps(report.to_dict(), indent=1))
        return
    from scripts.core.vault_bridge import _now
    print(f"HEALTH REPORT — {_now()[:10]}")
    print(f"errors: {len(report.errors)}   warnings: {len(report.warnings)}   "
          f"healthy: {len(report.healthy)}   checks: {report.checks_run}")
    if report.errors:
        print("\nERRORS")
        for i in report.errors:
            print(f"  • [{i.check}] {i.message}")
            print(f"      fix: {i.fix}")
    if report.warnings:
        print("\nWARNINGS")
        for i in report.warnings:
            print(f"  • [{i.check}] {i.message}")
            print(f"      fix: {i.fix}")
    print("\nHEALTHY")
    for name in report.healthy[:15]:
        print(f"  ✓ {name}")
    if len(report.healthy) > 15:
        print(f"  … and {len(report.healthy) - 15} more")
    if not report.errors:
        print("\nNo errors — graph is structurally sound.")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        prog="python -m scripts.core.health_check",
        description="Validate the Obsidian knowledge graph (detection only).")
    parser.add_argument("--vault", default=None, help="vault path")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)
    try:
        vault = Path(args.vault) if args.vault else (_REPO_ROOT / "obsidian_vault")
        if not vault.is_dir():
            print(f"error: vault not found: {vault}", file=sys.stderr)
            return 2
        report = run_health(vault)
        print_report(report, json_out=args.json)
        log_report(report)
        return 1 if report.errors else 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

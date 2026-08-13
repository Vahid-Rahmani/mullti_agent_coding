"""ContextResolver — bounded, typed context resolution from a task node.

Starting from a specific task node, the resolver walks the vault's
[[WikiLink]] graph outward (breadth-first, deterministic order) and returns a
structured ContextPackage for the Orchestrator.

Safety and design guarantees:

  * MAX_DEPTH / MAX_NODES caps — the vault is never fully loaded.
  * Direct dependencies (depth 1) are always collected before deeper rings and
    are exempt from the type filter so a task's immediate Agent / Component /
    sibling-task links are never dropped.
  * Deeper rings keep only the six relevant node kinds (agent, architecture,
    decision, documentation, test — plus system nodes that carry architecture
    context); task/hub nodes deeper than depth 1 are pruned.
  * Cycles are detected via an on-path visited set; traversal terminates.
    Cycles are REPORTED in the package, never silently swallowed.
  * Markdown is parsed as data only — nothing is ever executed.
  * Every resolution is logged (one JSONL row) to _logs/context_log.jsonl.
  * Fully deterministic: sorted BFS order, no timestamps inside the package.
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from scripts.core.vault_bridge import (
    FRONTMATTER_RE,
    LINK_RE,
    VaultError,
    _find_node,
    _log,
    _now,
    parse_frontmatter,
    read_node,
    resolve_task,
    validate_vault,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTEXT_LOG = Path("_logs") / "context_log.jsonl"

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_NODES = 10
SNIPPET_LIMIT = 500

# Node types allowed beyond depth 1 (requirement 3's six relevant kinds,
# plus system nodes that hold architecture context).
_RELEVANT_TYPES = {"agent", "architecture", "decision", "documentation", "test", "system"}
# Hub/index/template files are navigation scaffolding, never context payload.
_SKIP_NAMES = ("_Home", "Task_Backlog", "_TASK_TEMPLATE", "_TEST_PLAN_TEMPLATE", "_TEST_REPORT_TEMPLATE")


@dataclass(frozen=True)
class NodeRef:
    """One node included in a context package."""

    name: str
    path: str          # absolute path (str for easy logging/serialization)
    type: str
    depth: int
    snippet: str


@dataclass
class ContextPackage:
    """Structured context for one task — deterministic and bounded."""

    root: str
    nodes: list[NodeRef] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    cycles: list[tuple[str, str]] = field(default_factory=list)
    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES

    def included_names(self) -> list[str]:
        return [n.name for n in self.nodes]

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "nodes": [n.__dict__ for n in self.nodes],
            "unresolved": self.unresolved,
            "cycles": [list(c) for c in self.cycles],
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
        }


# ---------------------------------------------------------------- low-level

def _node_type(path: Path) -> str:
    """The node's ``type`` frontmatter field ('unknown' if unreadable)."""
    try:
        fields, _body, _raw = read_node(path)
        return fields.get("type", "unknown")
    except VaultError:
        return "unknown"


def _snippet(path: Path) -> str:
    """First SNIPPET_LIMIT chars of the node body (read-only, safe)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        m = FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text
        body = body.strip()
        return body[:SNIPPET_LIMIT]
    except OSError:
        return "(unreadable)"


def _neighbors(vault: Path, path: Path) -> list[str]:
    """Outgoing [[WikiLink]] targets of one node (frontmatter + body, deduped).

    Hub/index/template files are excluded. Only names, in file order — the
    caller sorts for determinism.
    """
    try:
        fields, body, _raw = read_node(path)
    except VaultError:
        return []
    wanted: list[str] = []
    for key in ("assigned_agent", "related_component", "related_agent",
                "related_task", "parent", "related"):
        val = (fields.get(key) or "").strip()
        if val:
            wanted.append(val)
    for m in LINK_RE.finditer(body):
        target = m.group(1).strip()
        if target:
            wanted.append(target)
    out: list[str] = []
    for name in wanted:
        if name.endswith(_SKIP_NAMES):
            continue
        if name not in out:
            out.append(name)
    return out


def _resolve_name(vault: Path, name: str) -> Path | None:
    return _find_node(vault, name)


# ---------------------------------------------------------------- resolver

def resolve_context(vault: Path, task_path: Path,
                    max_depth: int = DEFAULT_MAX_DEPTH,
                    max_nodes: int = DEFAULT_MAX_NODES) -> ContextPackage:
    """BFS from a task node -> bounded, typed, deterministic ContextPackage.

    * The task node itself is the root (not included in ``nodes``).
    * Depth 1 (direct links) is always fully collected first and is exempt
      from the type filter.
    * Depth > 1 keeps only relevant node kinds (see _RELEVANT_TYPES).
    * Cycles are detected via the on-path visited set and reported.
    * ``unresolved`` lists link targets with no matching file in the vault.
    """
    validate_vault(vault)
    if max_depth < 1:
        max_depth = 1
    if max_nodes < 1:
        max_nodes = 1
    if not task_path.is_file():
        raise VaultError(f"task node not found: {task_path}")

    package = ContextPackage(root=task_path.stem, max_depth=max_depth,
                             max_nodes=max_nodes)

    # BFS state: (name, depth, is_direct_ring).
    queue: deque[tuple[str, int]] = deque()
    visited: set[str] = set()
    on_path: set[str] = set()

    root_neighbors = sorted(_neighbors(vault, task_path))
    unresolved_seen: set[str] = set()
    for name in root_neighbors:
        hit = _resolve_name(vault, name)
        if hit is None:
            if name not in unresolved_seen:
                unresolved_seen.add(name)
                package.unresolved.append(name)
            continue
        if name == task_path.stem:
            # Task links back to itself -> genuine self-cycle at the root.
            package.cycles.append((task_path.stem, task_path.stem))
            continue
        if name in visited:
            continue  # already discovered via another ring — not a cycle
        visited.add(name)
        queue.append((name, 1))

    while queue and len(package.nodes) < max_nodes:
        name, depth = queue.popleft()
        hit = _resolve_name(vault, name)
        if hit is None:
            continue  # already recorded as unresolved from the parent ring
        ntype = _node_type(hit)
        is_direct = depth == 1
        if not is_direct and ntype not in _RELEVANT_TYPES:
            continue  # deeper rings: keep only relevant kinds (req 3 + 4)
        if len(package.nodes) >= max_nodes:
            break
        package.nodes.append(NodeRef(name=name, path=str(hit), type=ntype,
                                     depth=depth, snippet=_snippet(hit)))
        if depth >= max_depth:
            continue
        # Expand this node's neighbors. A true cycle is a back-edge to a node
        # currently on the path from the root to here; revisiting a node that
        # was merely discovered via another branch is a DAG, not a cycle.
        on_path.add(name)
        for target in sorted(_neighbors(vault, hit)):
            thit = _resolve_name(vault, target)
            if thit is None:
                if target not in unresolved_seen:
                    unresolved_seen.add(target)
                    package.unresolved.append(target)
                continue
            if target in on_path:
                package.cycles.append((name, target))
                continue
            if target in visited:
                continue  # shared descendant via another branch — not a cycle
            visited.add(target)
            queue.append((target, depth + 1))
        on_path.discard(name)

    # Any remaining queued nodes are dropped by the cap — that is intended.
    log_context(package)
    return package


# ---------------------------------------------------------------- logging

def log_context(package: ContextPackage) -> None:
    """Append one JSONL row per resolution to _logs/context_log.jsonl."""
    record = {
        "ts": _now(),
        "task": package.root,
        "max_depth": package.max_depth,
        "max_nodes": package.max_nodes,
        "included": package.included_names(),
        "unresolved": package.unresolved,
        "cycles": [list(c) for c in package.cycles],
    }
    try:
        path = _REPO_ROOT / CONTEXT_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError) as exc:
        _log(f"context_resolver: context-log append failed: {exc}")


# ---------------------------------------------------------------- CLI surface

def cmd_context(vault: Path, name: str, max_depth: int,
                max_nodes: int) -> int:
    """CLI: print the resolved context package for a task node."""
    task_path = resolve_task(vault, name)
    if task_path is None:
        raise VaultError(f"invalid task name: {name!r}")
    package = resolve_context(vault, task_path, max_depth=max_depth,
                              max_nodes=max_nodes)
    print(f"# Context for [[{package.root}]] "
          f"(depth<={package.max_depth}, nodes<={package.max_nodes})")
    if not package.nodes:
        print("(no linked context resolved)")
    for ref in package.nodes:
        print(f"  d{ref.depth} [{ref.type:<13}] {ref.name}")
        if ref.snippet:
            first = ref.snippet.splitlines()[0][:80]
            print(f"      {first}")
    if package.unresolved:
        print(f"unresolved: {', '.join(package.unresolved)}")
    if package.cycles:
        print(f"cycles: {', '.join(f'{a}->{b}' for a, b in package.cycles)}")
    return 0


__all__ = [
    "CONTEXT_LOG",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "SNIPPET_LIMIT",
    "ContextPackage",
    "NodeRef",
    "cmd_context",
    "log_context",
    "resolve_context",
    "_neighbors",
    "_node_type",
    "_snippet",
]

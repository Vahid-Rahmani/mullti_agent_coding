"""VaultGraph — read-only node/edge model of the managed Obsidian vault.

The dashboard renders the vault's knowledge graph from existing link data.
Node set: the seven managed sections (00-System .. 06-Testing) plus the
vault-root Dashboard/Roadmap nodes; template files (underscore-prefixed) and
the ``prompts/`` / ``agents_logs/`` archives are excluded. Edges are
[[WikiLink]] adjacencies resolved against the node set — no new backend
capability, just a read-only view of link structure the vault already keeps.

Everything here is read-only; writes continue to go through VaultBridge.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from scripts.core.vault_bridge import (
    FRONTMATTER_RE,
    LINK_RE,
    VaultError,
    _find_node,
    parse_frontmatter,
)

SECTIONS = (
    "00-System", "01-Architecture", "02-Agents", "03-Tasks",
    "04-Decisions", "05-Documentation", "06-Testing",
)

ROOT_NODES = ("Dashboard", "Roadmap")

SNIPPET_LIMIT = 120
_CACHE_TTL = 15  # seconds before the node graph is rebuilt

_CACHE: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------- node access


def find_node(vault: Path, name: str) -> Path | None:
    """Locate any managed node by name (vault root first, then sections)."""
    root_hit = vault / f"{name}.md"
    if root_hit.is_file():
        return root_hit
    return _find_node(vault, name)


def _raw(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _node_type(fields: dict[str, str]) -> str:
    return fields.get("type", "unknown") or "unknown"


def _snippet(raw: str) -> str:
    """First SNIPPET_LIMIT chars of the body (after the frontmatter block)."""
    m = FRONTMATTER_RE.match(raw)
    body = raw[m.end():] if m else raw
    body = body.strip()
    return body[:SNIPPET_LIMIT] or "(empty)"


def _related_links(fields: dict[str, str]) -> list[str]:
    """Real relationships declared as ``related: [A, B]`` frontmatter.

    The vault schema (Node_Schema_Reference) keeps a ``related`` list alongside
    body WikiLinks; both are genuine relationships, so both feed the graph.
    """
    raw = (fields.get("related") or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------- build


def build_nodes(vault: Path) -> list[dict]:
    """Node records: name, path, folder, type, degree, and raw link list."""
    nodes: list[dict] = []
    seen: set[str] = set()

    def add(file: Path, folder: str, name: str) -> None:
        if name in seen:
            return
        raw = _raw(file)
        fields: dict[str, str] = {}
        m = FRONTMATTER_RE.match(raw)
        if m:
            fields, _err = parse_frontmatter(raw)
        links = [t.strip() for t in LINK_RE.findall(raw) if t.strip()]
        links.extend(_related_links(fields))
        unique: list[str] = []
        for link in links:
            if link not in unique and link != name:
                unique.append(link)
        nodes.append({
            "name": name,
            "path": str(file.relative_to(vault)).replace(os.sep, "/"),
            "folder": folder,
            "type": _node_type(fields),
            "links": unique,
        })
        seen.add(name)

    for folder in SECTIONS:
        section = vault / folder
        if not section.is_dir():
            continue
        for file in sorted(section.glob("*.md")):
            if file.name.startswith("_"):
                continue
            add(file, folder, file.stem)

    for name in ROOT_NODES:
        file = vault / f"{name}.md"
        if file.is_file():
            add(file, "root", name)

    return nodes


def build_graph(vault: Path) -> dict:
    """Full graph: nodes (+degree) and edges ([[WikiLink]] adjacencies)."""
    nodes = build_nodes(vault)
    names = {n["name"] for n in nodes}
    edges: list[list[str]] = []
    degree = {n["name"]: 0 for n in nodes}
    for node in nodes:
        for target in node["links"]:
            if target not in names or target == node["name"]:
                continue
            edges.append([node["name"], target])
            degree[node["name"]] += 1
            degree[target] += 1
    for node in nodes:
        node["degree"] = degree[node["name"]]
    return {"nodes": nodes, "edges": edges}


def get_graph(vault: Path, refresh: bool = False, ttl: int = _CACHE_TTL) -> dict:
    """Build (or reuse) the node graph; cheap per-request after the TTL."""
    key = str(vault)
    cached = _CACHE.get(key)
    now = time.monotonic()
    if not refresh and cached is not None and (now - cached[0]) <= ttl:
        return cached[1]
    graph = build_graph(vault)
    _CACHE[key] = (now, graph)
    return graph


def invalidate_graph(vault: Path) -> None:
    _CACHE.pop(str(vault), None)


# ---------------------------------------------------------------- relationships


def node_relationships(vault: Path, name: str) -> dict:
    """Outgoing links + backlinks for one node (each with a snippet)."""
    path = find_node(vault, name)
    if path is None:
        raise VaultError(f"node not found: {name}")
    graph = get_graph(vault)
    names = {n["name"]: n for n in graph["nodes"]}
    raw = _raw(path)

    def summary(node_name: str) -> dict:
        node = names.get(node_name)
        rel = os.path.join("root", node_name + ".md") if node is None else node["path"]
        node_path = find_node(vault, node_name)
        node_raw = _raw(node_path) if node_path else ""
        return {
            "name": node_name,
            "type": node["type"] if node else "unknown",
            "folder": node["folder"] if node else "root",
            "path": rel,
            "snippet": _snippet(node_raw),
        }

    links = [
        summary(link) for link in
        (t.strip() for t in LINK_RE.findall(raw) if t.strip())
        if link in names and link != name
    ]
    backlinks = [
        summary(node["name"]) for node in graph["nodes"]
        if node["name"] != name and name in node["links"]
    ]

    fields: dict[str, str] = {}
    m = FRONTMATTER_RE.match(raw)
    if m:
        fields, _err = parse_frontmatter(raw)
    return {
        "node": {
            "name": name,
            "type": fields.get("type", "unknown"),
            "folder": "root" if path.parent == vault else path.parent.name,
            "path": str(path.relative_to(vault)).replace(os.sep, "/"),
        },
        "links": links,
        "backlinks": backlinks,
    }


__all__ = [
    "ROOT_NODES",
    "SECTIONS",
    "SNIPPET_LIMIT",
    "build_graph",
    "build_nodes",
    "find_node",
    "get_graph",
    "invalidate_graph",
    "node_relationships",
]
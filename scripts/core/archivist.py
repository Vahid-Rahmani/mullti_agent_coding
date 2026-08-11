"""Architectural Obsidian Archivist — M7 Chloe's host-side documentation engine.

Deterministic, pure-stdlib implementation of the five strict rules of the
Architectural Obsidian Archivist:

1. **Intelligent Filtering** — conversational text is ignored; only
   architectural decisions, system mappings, and technical milestones are
   captured.
2. **Context-Aware Storage** — notes are never written into the agent's own
   directory (``obsidian_vault/agents_logs/``). The project directory of the
   current task is resolved and notes are stored under
   ``<project>/docs/architecture/``.
3. **Graph Mapping** — every project note embeds a Mermaid.js flowchart that
   maps the current code architecture (host-side deterministic auto-scan).
4. **Maintenance Duty** — the architecture note stays in sync with the real
   code structure; when the structure fingerprint changes (a refactor), the
   map is regenerated.
5. **Optimization** — repetitive logs are summarized into a single lean
   ``Evolution.md`` per project; the vault stays small.

No third-party imports; atomic writes via tempfile + os.replace; safe to
call from any thread.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .agents import PROJECT_ROOT

# --------------------------------------------------------------------------- constants

# Rule 2 — notes live under the resolved project directory, never the agent's own.
DOCS_DIR_NAME = "docs/architecture"
ARCHITECTURE_NOTE = "Architecture.md"
EVOLUTION_NOTE = "Evolution.md"

# Rule 5 — cap per-project evolution entries; older ones are summarized.
MAX_EVOLUTION_ENTRIES = 40

# Rule 3 — bounded deterministic scan (keeps the map lean, Rule 5).
MAX_MAP_NODES = 60
MAX_MAP_DEPTH = 3

# --------------------------------------------------------------------------- Rule 1: filtering

_ARCHITECTURAL_KEYWORDS = (
    "decision", "decided", "architecture", "architect", "schema", "refactor",
    "refactoring", "migrat", "mapping", "map ", "routing", "milestone", "module",
    "component", "interface", "api", "endpoint", "contract", "dependency",
    "data model", "data-model", "layer", "integration", "adr", "blueprint",
    "design", "structure", "flow", "protocol", "payload", "queue", "event",
    "pub/sub", "rest", "graphql", "database", "table", "index", "service",
    "microservice", "monolith", "state machine",
)

_MILESTONE_KEYWORDS = (
    "released", "shipped", "v1.0", "v2.0", "version", "milestone", "phase",
    "completed", "delivered", "landed", "launched",
)

_CONVERSATIONAL_MARKERS = (
    "hello", "hi ", "hey", "thanks", "thank you", "great", "cool", "awesome",
    "nice", "good morning", "good afternoon", "good evening", "how are you",
    "please", "sure", "okay", "well done", "congrats", "sounds good",
    "works", "perfect", "love it",
)

# Strong whole-prompt signals that survive even when no single line matches.
_STRONG_SIGNALS = ("refactor", "architecture", "migrate", "milestone", "decision")


def _classify_line(line: str) -> str:
    """Classify one text line: architectural / milestone / conversational / neutral."""
    lowered = line.lower().strip(" .!?")
    if not lowered or len(lowered) < 4:
        return "conversational"
    has_arch = any(k in lowered for k in _ARCHITECTURAL_KEYWORDS)
    has_mile = any(m in lowered for m in _MILESTONE_KEYWORDS)
    if has_arch or has_mile:
        return "architectural" if has_arch else "milestone"
    if any(m in lowered for m in _CONVERSATIONAL_MARKERS):
        return "conversational"
    return "neutral"


def filter_archival_content(text: str) -> dict:
    """Rule 1 — return only architectural content worth archiving.

    Returns ``{"archived": bool, "entries": list[str], "reason": str}``.
    Conversational prompts yield ``archived=False`` and no entries.
    """
    if not text or not text.strip():
        return {"archived": False, "entries": [], "reason": "empty prompt"}

    kept: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _classify_line(line) in ("architectural", "milestone"):
            kept.append(line)

    # Whole-prompt fallback: strong architectural wording overrides line rules.
    if not kept and any(s in text.lower() for s in _STRONG_SIGNALS):
        kept = [text.strip()]

    if not kept:
        return {
            "archived": False,
            "entries": [],
            "reason": "conversational or no architectural signal",
        }

    # Dedupe preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for entry in kept:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return {
        "archived": True,
        "entries": unique,
        "reason": f"{len(unique)} architectural line(s) captured",
    }


# --------------------------------------------------------------------------- Rule 2: storage

_PATH_HINT_RE = re.compile(
    r"(?:in|under|at|for|path|dir|project)\s+[\"']?([\w\-.\\/:]+)[\"']?",
    re.IGNORECASE,
)


def _looks_like_project(path: Path) -> bool:
    """A directory is project-worthy when it holds code or is a projects/ child."""
    if not path.is_dir():
        return False
    try:
        any(path.iterdir())
    except OSError:
        return False
    return True


def _sane_project(candidate: Path, workspace: Path) -> Path:
    """Rule 2 guard — never resolve inside the archivist's own agent directory."""
    candidate = Path(candidate).resolve()
    workspace = Path(workspace).resolve()
    own_logs = workspace / "obsidian_vault" / "agents_logs"
    try:
        candidate.relative_to(own_logs)
    except ValueError:
        return candidate
    return workspace


def resolve_project_dir(prompt: str, workspace: Path | None = None) -> Path:
    """Rule 2 — resolve the project directory of the current task.

    Resolution order:
    1. explicit absolute paths mentioned in the prompt,
    2. relative paths / path hints mentioned in the prompt,
    3. existing ``<workspace>/projects/<name>`` subdirectories whose name
       appears in the prompt,
    4. fallback: the active workspace.

    Never returns a directory inside ``obsidian_vault/agents_logs/``.
    """
    workspace = Path(workspace) if workspace is not None else PROJECT_ROOT

    candidates: list[Path] = []
    # Windows absolute paths (C:\...)
    candidates += [
        Path(m.group(0)) for m in re.finditer(r"[A-Za-z]:[\\/][^\s\"']+", prompt)
    ]
    # POSIX absolute paths (/...)
    candidates += [
        Path(m.group(0)) for m in re.finditer(r"(?<!\w)/[\w\-./\\]+", prompt)
    ]
    # in/under/at/for/path/dir/project hints
    candidates += [Path(m.group(1)) for m in _PATH_HINT_RE.finditer(prompt)]

    for cand in candidates:
        cand = Path(cand).expanduser()
        if cand.is_absolute() and _looks_like_project(cand):
            return _sane_project(cand, workspace)
        rel = (workspace / cand).resolve()
        if _looks_like_project(rel):
            return _sane_project(rel, workspace)

    # Projects registry: workspace/projects/<name> mentioned by name.
    projects_dir = workspace / "projects"
    if projects_dir.is_dir():
        prompt_lower = prompt.lower()
        for child in sorted(projects_dir.iterdir()):
            if child.is_dir() and child.name.lower() in prompt_lower:
                return _sane_project(child, workspace)

    return _sane_project(workspace, workspace)


_WRITE_LOCK = threading.Lock()


def docs_dir(project_dir: Path) -> Path:
    """Rule 2 — canonical notes folder inside a project.

    Refuses to resolve into an ``agents_logs`` directory (the archivist's own
    agent-log folder) even when called directly with a hostile path.
    """
    resolved = Path(project_dir).resolve()
    if any(part.lower() == "agents_logs" for part in resolved.parts):
        raise ValueError(f"refusing to write into agent directory: {resolved}")
    return resolved / DOCS_DIR_NAME


# --------------------------------------------------------------------------- Rule 3: mermaid map

_SKIP_DIR_NAMES = {
    ".git", ".obsidian", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".hive", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "_logs", "knowledge", "obsidian_vault", ".opencode",
}
_SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".lock", ".tmp2"}

_INCLUDE_SUFFIXES = {
    ".py", ".bat", ".sh", ".ps1", ".json", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".md",
}


def _scan_tree(project_dir: Path, max_depth: int = MAX_MAP_DEPTH, max_nodes: int = MAX_MAP_NODES) -> list[tuple[str, str]]:
    """Deterministic sorted walk; returns [(relpath, 'dir'|'file'), ...]."""
    nodes: list[tuple[str, str]] = []
    project_dir = Path(project_dir)

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth or len(nodes) >= max_nodes:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for entry in entries:
            if len(nodes) >= max_nodes:
                return
            name = entry.name
            if name.startswith(".") and name != ".gitignore":
                continue
            # Never map the archivist's own output folder.
            if name == "architecture" and entry.parent.name == "docs":
                continue
            if entry.is_dir():
                if name in _SKIP_DIR_NAMES:
                    continue
                rel = str(entry.relative_to(project_dir)).replace("\\", "/")
                nodes.append((rel, "dir"))
                walk(entry, depth + 1)
            else:
                if entry.suffix.lower() in _SKIP_FILE_SUFFIXES:
                    continue
                if entry.suffix.lower() in _INCLUDE_SUFFIXES:
                    rel = str(entry.relative_to(project_dir)).replace("\\", "/")
                    nodes.append((rel, "file"))

    walk(project_dir, 0)
    return nodes[:max_nodes]


def _mermaid_node_id(rel: str) -> str:
    """Sanitize a relative path into a valid mermaid node identifier."""
    ident = re.sub(r"[^A-Za-z0-9_]", "_", rel).strip("_") or "node"
    return f"N_{ident[:40]}"


def _mermaid_label(text: str) -> str:
    """Escape a mermaid double-quoted label."""
    return text.replace('"', "'").replace("\\", "/")


def generate_mermaid_map(
    project_dir: Path,
    max_depth: int = MAX_MAP_DEPTH,
    max_nodes: int = MAX_MAP_NODES,
) -> str:
    """Rule 3 — render a Mermaid flowchart of the current code architecture.

    Deterministic host-side auto-scan: the project root node connects to
    top-level entries, which connect to their mapped children.
    """
    nodes = _scan_tree(project_dir, max_depth, max_nodes)
    root_name = Path(project_dir).name or "project"

    lines = ["flowchart TD", f'    ROOT["{_mermaid_label(root_name)}"]']
    emitted: set[str] = {"ROOT"}
    counters: dict[str, int] = {}
    rel_to_id: dict[str, str] = {}

    def unique_id(rel: str) -> str:
        """Stable node id per relative path; collision counter for deep paths."""
        if rel in rel_to_id:
            return rel_to_id[rel]
        base = _mermaid_node_id(rel)
        index = counters.get(base, 0)
        counters[base] = index + 1
        nid = base if index == 0 else f"{base}_{index}"
        rel_to_id[rel] = nid
        return nid

    for rel, _kind in nodes:
        nid = unique_id(rel)
        if nid in emitted:
            continue
        parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else None
        pid = unique_id(parent_rel) if parent_rel else "ROOT"
        if pid not in emitted:
            pid = "ROOT"
        lines.append(f'    {pid} --> {nid}["{_mermaid_label(rel)}"]')
        emitted.add(nid)

    return "```mermaid\n" + "\n".join(lines) + "\n```"


def structure_fingerprint(project_dir: Path) -> str:
    """Deterministic hash of the current structure (Rule 4 drift detection)."""
    nodes = _scan_tree(Path(project_dir))
    canonical = "\n".join(f"{kind}:{rel}" for rel, kind in nodes)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- Rule 4: maintenance

_FINGERPRINT_RE = re.compile(r"<!-- fingerprint: ([0-9a-f]+) -->")


def _render_architecture_note(
    project_dir: Path,
    fingerprint: str,
    map_src: str,
    entries: list[str],
    prompt: str,
) -> str:
    """Render the per-project Architecture.md (map + captured decisions)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {project_dir.name} — Architecture",
        "",
        "> Maintained by the Architectural Obsidian Archivist (M7).",
        f"> Last synced: {now}",
        f"<!-- fingerprint: {fingerprint} -->",
        "",
        "## Decisions & Milestones",
        "",
    ]
    if entries:
        lines += [f"- {entry}" for entry in entries]
    elif filter_archival_content(prompt)["archived"]:
        lines.append(f"- {prompt.strip()[:140]}")
    else:
        lines.append("_No architectural decisions captured yet._")
    lines += ["", "## System Map", "", map_src, ""]
    return "\n".join(lines)


def sync_architecture_docs(
    project_dir: Path,
    entries: list[str] | None = None,
    prompt: str = "",
) -> dict:
    """Rule 4 — keep the project's architecture note in sync with the code.

    Regenerates ``docs/architecture/Architecture.md`` (with its embedded
    Mermaid map) whenever the structure fingerprint changed — i.e. after a
    refactor — or when the note does not exist yet.
    """
    project_dir = Path(project_dir)
    directory = docs_dir(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
    note = directory / ARCHITECTURE_NOTE

    fingerprint = structure_fingerprint(project_dir)

    existing_fp: str | None = None
    if note.exists():
        match = _FINGERPRINT_RE.search(note.read_text(encoding="utf-8", errors="replace"))
        existing_fp = match.group(1) if match else None

    changed = existing_fp != fingerprint
    if changed:
        map_src = generate_mermaid_map(project_dir)
        body = _render_architecture_note(
            project_dir, fingerprint, map_src, entries or [], prompt,
        )
        with _WRITE_LOCK:
            _atomic_write(note, body)

    return {
        "ok": True,
        "map_regenerated": changed,
        "fingerprint": fingerprint,
        "note_path": str(note),
    }


# --------------------------------------------------------------------------- Rule 5: optimization

def _squash(entry: str, limit: int = 120) -> str:
    """One-line squash of a captured entry (keeps notes lean)."""
    one_line = " ".join(entry.split())
    return one_line[:limit] + ("…" if len(one_line) > limit else "")


def consolidate_evolution(
    project_dir: Path,
    entries: list[str],
    prompt: str = "",
) -> dict:
    """Rule 5 — maintain a single lean ``Evolution.md`` per project.

    Dedupes repetitive entries, prepends new ones, and summarizes overflow
    beyond ``MAX_EVOLUTION_ENTRIES`` into one compact line.
    """
    project_dir = Path(project_dir)
    directory = docs_dir(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
    note = directory / EVOLUTION_NOTE
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    existing: list[str] = []
    if note.exists():
        existing = [
            line for line in note.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("- ")
        ]

    # Rule 5 — dedupe by *content*, not by timestamp: re-archiving the same
    # decision must never grow the file.
    def _content(line: str) -> str:
        return line.split(" — ", 1)[1] if " — " in line else line[2:]

    existing_contents = {_content(line) for line in existing}
    new_contents: set[str] = set()

    new_lines: list[str] = []
    sources = list(entries) if entries else ([prompt] if prompt.strip() else [])
    for entry in sources:
        squashed = _squash(entry)
        if squashed in existing_contents or squashed in new_contents:
            continue
        line = f"- {now} — {squashed}"
        new_lines.append(line)
        new_contents.add(squashed)

    if not new_lines:
        return {
            "ok": True,
            "evolution_path": str(note),
            "appended": 0,
            "total": len(existing),
        }

    combined = new_lines + existing
    total = len(combined)
    if len(combined) > MAX_EVOLUTION_ENTRIES:
        excess = len(combined) - MAX_EVOLUTION_ENTRIES
        combined = [f"- … {excess} earlier entries summarized"] + combined[:MAX_EVOLUTION_ENTRIES]
        total = len(combined)

    body = [
        "# Evolution",
        "",
        "> Single lean per-project history, maintained by the Architectural Obsidian Archivist (M7).",
        "",
        *combined,
        "",
    ]
    with _WRITE_LOCK:
        _atomic_write(note, "\n".join(body))

    return {
        "ok": True,
        "evolution_path": str(note),
        "appended": len(new_lines),
        "total": total,
    }


# --------------------------------------------------------------------------- master entry

def archivist_run(
    prompt: str = "",
    workspace: Path | None = None,
    project_dir: Path | None = None,
    plan: object | None = None,
) -> dict:
    """Run the full archivist pipeline for one dispatch (or the /archive command).

    Always syncs the architecture map (Rule 4); only captures decisions and
    milestones when the prompt carries architectural signal (Rule 1). When the
    Analyzer Core provided a ``MasterPlan``, its module map (one component per
    agent) is persisted first as the architecture mapping for the task.
    Writes land under the resolved project's ``docs/architecture/`` (Rule 2).
    """
    workspace = Path(workspace) if workspace is not None else PROJECT_ROOT
    filtered = filter_archival_content(prompt)
    project = (
        _sane_project(Path(project_dir), workspace)
        if project_dir is not None
        else resolve_project_dir(prompt, workspace)
    )

    entries = list(filtered["entries"])
    plan_entries = getattr(plan, "archivist_entries", lambda: [])() if plan is not None else []
    entries = list(plan_entries) + entries

    sync = sync_architecture_docs(project, entries=entries, prompt=prompt)
    if filtered["archived"] or plan_entries:
        evolution = consolidate_evolution(project, entries, prompt=prompt)
    else:
        evolution = {
            "ok": True,
            "evolution_path": str(docs_dir(project) / EVOLUTION_NOTE),
            "appended": 0,
            "total": 0,
        }

    summary_lines = [
        f"Archivist (M7): project={project}",
        f"  filter: {filtered['reason']}",
        f"  architecture map: {'regenerated (structure changed)' if sync['map_regenerated'] else 'up to date'}",
        f"  evolution: +{evolution['appended']} entry(ies) → {evolution['evolution_path']}",
    ]
    if plan_entries:
        summary_lines.append(f"  analyzer plan: {len(plan_entries)} module mapping(s) persisted")
    summary = "\n".join(summary_lines)

    return {
        "ok": True,
        "archived": filtered["archived"],
        "project_dir": str(project),
        "filter": filtered,
        "sync": sync,
        "evolution": evolution,
        "summary": summary,
    }


# --------------------------------------------------------------------------- helpers

def _atomic_write(path: Path, content: str) -> None:
    """Atomic write via temp file + os.replace (crash-safe)."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".archivist.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

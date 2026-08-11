"""ChangeDetector — safe, snapshot-based detection of vault + project changes.

Design (Phase 15):

  * SNAPSHOT-based: a full scan produces {rel_path: (mtime_ns, sha256)}; two
    snapshots are diffed. No watchdogs, no daemons, fully deterministic.
  * DETECTION ONLY: never auto-executes an agent, never modifies or deletes
    user files (the only writes are to _logs/).
  * Four change kinds: created / modified / renamed / deleted. A rename is
    detected when one path disappears and an identical-content path appears.
  * Classification maps every changed path to one of: documentation,
    architecture, task, agent, source code, configuration, test.
  * Cross-impact: for a project change, find the Obsidian nodes that link the
    affected component; for an Obsidian change, find the linked component
    nodes. Bounded reads only.
  * Duplicate prevention: a (path, kind, content-hash) dedupe key; running
    detect twice against the same snapshot yields zero new changes the second
    time.
  * Editor/temp-file safety: *.tmp, *.swp, *~, *.bak, ~$* (Office locks),
    _logs/, .git/, .opencode/ are excluded from snapshots.

CLI (from the repo root):

    python -m scripts.core.change_detector snapshot [--vault P]
    python -m scripts.core.change_detector detect [--vault P]
    python -m scripts.core.change_detector classify <path>
    python -m scripts.core.change_detector affected <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_DIR = Path("_logs") / "snapshots"
CHANGE_LOG = Path("_logs") / "change_log.jsonl"

# ---------------------------------------------------------------- constants

# Excluded from BOTH vault and project snapshots (editor/temp/log noise).
_EXCLUDE_DIRS = {".git", ".opencode", "_logs", "node_modules", ".venv", "__pycache__"}
_EXCLUDE_SUFFIXES = {".tmp", ".swp", ".swo", ".bak", ".pyc", ".pyo", ".log"}
_EXCLUDE_PATTERNS = [
    re.compile(r".*~$"),          # editor backup files
    re.compile(r"^~\$"),          # Office/editor lock files
]

# Vault section -> classification (relative to the vault root).
_VAULT_SECTION_CLASS = {
    "00-System": "documentation",
    "01-Architecture": "architecture",
    "02-Agents": "agent",
    "03-Tasks": "task",
    "04-Decisions": "architecture",     # decisions are architecture knowledge
    "05-Documentation": "documentation",
    "06-Testing": "test",
}

_SOURCE_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
                    ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".sh"}
# Script/launcher files are configuration-ish (deployment surface), not source.
_SCRIPT_SUFFIXES = {".ps1", ".bat", ".cmd"}
_CONFIG_SUFFIXES = {".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml"}
_TEST_PATH_PARTS = ("test", "tests", "spec")


class ChangeKind:
    CREATED = "created"
    MODIFIED = "modified"
    RENAMED = "renamed"
    DELETED = "deleted"


@dataclass
class Change:
    path: str
    kind: str
    classification: str
    old_hash: str = ""
    new_hash: str = ""

    @property
    def dedupe_key(self) -> str:
        return f"{self.path}|{self.kind}|{self.new_hash or self.old_hash}"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class DetectionResult:
    changes: list[Change] = field(default_factory=list)
    snapshot_path: str = ""

    def to_dict(self) -> dict:
        return {"snapshot": self.snapshot_path,
                "changes": [c.to_dict() for c in self.changes]}


# ---------------------------------------------------------------- snapshot

def _excluded(rel: Path) -> bool:
    """True for editor/temp/noise files and excluded directories."""
    name = rel.name
    if rel.suffix.lower() in _EXCLUDE_SUFFIXES:
        return True
    for pat in _EXCLUDE_PATTERNS:
        if pat.match(name):
            return True
    return any(part in _EXCLUDE_DIRS for part in rel.parts)


def _file_digest(path: Path) -> str:
    """sha256 of file content (read-only)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _snapshot_tree(root: Path, include_suffixes: set[str] | None = None) -> dict[str, tuple[int, str]]:
    """Walk a tree -> {rel_path: (mtime_ns, sha256)}. Read-only, bounded."""
    snap: dict[str, tuple[int, str]] = {}
    if not root.is_dir():
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _EXCLUDE_DIRS)
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            rel = full.relative_to(root)
            if _excluded(rel):
                continue
            if include_suffixes and rel.suffix.lower() not in include_suffixes:
                continue
            try:
                st = full.stat()
            except OSError:
                continue
            snap[str(rel).replace(os.sep, "/")] = (st.st_mtime_ns, _file_digest(full))
    return snap


def snapshot(vault: Path | None = None, project_root: Path | None = None) -> dict:
    """Full snapshot: vault markdown + project files (vault excluded from project).

    Returns a serializable dict, written to _logs/snapshots/<ts>.json.
    """
    vault = Path(vault) if vault else (_REPO_ROOT / "obsidian_vault")
    project = Path(project_root) if project_root else _REPO_ROOT

    vault_snap = _snapshot_tree(vault, include_suffixes={".md"})
    # Project pass: exclude the vault and _logs (already covered / noise).
    project_excl = _EXCLUDE_DIRS | {"obsidian_vault"}
    project_snap: dict[str, tuple[int, str]] = {}
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in project_excl and not d.startswith("."))
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            rel = full.relative_to(project)
            if _excluded(rel) or rel.suffix.lower() not in (
                    _SOURCE_SUFFIXES | _CONFIG_SUFFIXES | {".md"}):
                continue
            try:
                st = full.stat()
            except OSError:
                continue
            project_snap[str(rel).replace(os.sep, "/")] = (st.st_mtime_ns, _file_digest(full))

    data = {
        "vault_root": str(vault.resolve()),
        "project_root": str(project.resolve()),
        "vault": vault_snap,
        "project": project_snap,
    }
    snap_dir = _REPO_ROOT / SNAPSHOT_DIR
    snap_dir.mkdir(parents=True, exist_ok=True)
    from scripts.core.vault_bridge import _now
    ts = _now().replace(":", "-")
    out = snap_dir / f"snapshot-{ts}.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


# ---------------------------------------------------------------- diff

def _diff_snap(before: dict[str, tuple[int, str]],
               after: dict[str, tuple[int, str]],
               classify_fn) -> list[Change]:
    """Diff two snapshots. Renames pair identical-content delete+create;
    when content differs too, the pair is reported as delete+create instead."""
    changes: list[Change] = []
    before_keys = set(before)
    after_keys = set(after)

    # Deleted + candidates for rename (disappeared paths).
    deleted = before_keys - after_keys
    # Created + candidates for rename (new paths).
    created = after_keys - before_keys

    # Rename heuristic: a deleted path whose content hash appears among the
    # created paths (content identical, location moved).
    created_hash_map: dict[str, str] = {k: after[k][1] for k in created}
    hash_to_created: dict[str, list[str]] = {}
    for path, digest in created_hash_map.items():
        hash_to_created.setdefault(digest, []).append(path)
    matched_deleted: set[str] = set()

    for dpath in sorted(deleted):
        dhash = before[dpath][1]
        if dhash and dhash in hash_to_created:
            # Rename: pick the first created path with the same content.
            new_path = hash_to_created[dhash][0]
            changes.append(Change(
                path=f"{dpath} -> {new_path}", kind=ChangeKind.RENAMED,
                classification=classify_fn(new_path),
                old_hash=dhash, new_hash=dhash))
            matched_deleted.add(dpath)
            hash_to_created[dhash].remove(new_path)
            if not hash_to_created[dhash]:
                del hash_to_created[dhash]
            created.discard(new_path)

    for dpath in sorted(deleted - matched_deleted):
        changes.append(Change(path=dpath, kind=ChangeKind.DELETED,
                              classification=classify_fn(dpath),
                              old_hash=before[dpath][1]))

    for cpath in sorted(created):
        changes.append(Change(path=cpath, kind=ChangeKind.CREATED,
                              classification=classify_fn(cpath),
                              new_hash=after[cpath][1]))

    # Modified: present in both with different content hashes.
    for mpath in sorted(before_keys & after_keys):
        if before[mpath][1] != after[mpath][1]:
            changes.append(Change(path=mpath, kind=ChangeKind.MODIFIED,
                                  classification=classify_fn(mpath),
                                  old_hash=before[mpath][1], new_hash=after[mpath][1]))
    return changes


# ---------------------------------------------------------------- classification

def classify(rel_path: str) -> str:
    """Map a relative path to a change classification."""
    parts = rel_path.replace("\\", "/").split("/")
    top = parts[0] if parts else ""
    if top in _VAULT_SECTION_CLASS:
        return _VAULT_SECTION_CLASS[top]
    suffix = Path(rel_path).suffix.lower()
    if any(t in parts for t in _TEST_PATH_PARTS) and suffix in _SOURCE_SUFFIXES:
        return "test"
    if suffix in _SOURCE_SUFFIXES:
        return "source code"
    if suffix in _CONFIG_SUFFIXES or suffix in _SCRIPT_SUFFIXES:
        return "configuration"
    if suffix == ".md":
        return "documentation"
    return "source code" if suffix else "configuration"


# ---------------------------------------------------------------- cross-impact

def affected_nodes(vault: Path, rel_path: str) -> list[str]:
    """Project change -> Obsidian nodes with a REAL dependency on the component.

    A node is affected only when the changed component is named in its
    frontmatter (``related_component`` / ``related_agent`` / ``parent``) or in
    a body ``[[WikiLink]]`` — a raw substring hit (e.g. a hub's children
    index) is NOT a dependency. Hub/index files are skipped entirely.
    """
    stem = Path(rel_path).stem
    component = re.sub(r"[_-]+", "_", stem)
    camel = "".join(part[:1].upper() + part[1:] for part in component.split("_"))
    tokens = {component, stem, camel, f"Component_{camel}"}
    hits: list[str] = []
    for section in sorted(_VAULT_SECTION_CLASS):
        folder = vault / section
        if not folder.is_dir():
            continue
        for node_file in sorted(folder.glob("*.md")):
            name = node_file.stem
            if node_file.name.startswith("_") or name.endswith(("_Home", "_Index")) \
                    or name in ("Task_Backlog", "Node_Schema_Reference"):
                continue
            try:
                text = node_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Dependency check: frontmatter link fields OR body [[WikiLinks]] only.
            fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
            fm_text = fm.group(1) if fm else ""
            body = text[fm.end():] if fm else text
            dep_text = fm_text + " " + " ".join(
                m.group(1) for m in re.finditer(r"\[\[([^|\]]+)\]\]", body))
            if any(tok in dep_text for tok in tokens):
                hits.append(f"{section}/{name}")
    return hits


def affected_components(vault: Path, vault_rel_path: str) -> list[str]:
    """Obsidian change -> component nodes linked from the changed node."""
    rel = Path(vault_rel_path)
    section = rel.parts[0] if rel.parts else ""
    node_file = vault / section / rel.name if section in _VAULT_SECTION_CLASS else None
    if node_file is None or not node_file.is_file():
        return []
    try:
        text = node_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names = re.findall(r"\[\[([^|\]]+)\]\]", text)
    out: list[str] = []
    for n in names:
        if n.startswith("Component_"):
            out.append(n)
    return sorted(set(out))


# ---------------------------------------------------------------- logging

def log_detection(result: DetectionResult) -> None:
    """Append one JSONL row per detection run (dedupe at the record level)."""
    record = {
        "ts": _now_ts(),
        "snapshot": result.snapshot_path,
        "count": len(result.changes),
        "changes": [c.to_dict() for c in result.changes],
    }
    try:
        path = _REPO_ROOT / CHANGE_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError):
        pass  # logging must never break detection


def _now_ts() -> str:
    from scripts.core.vault_bridge import _now
    return _now()


def _load_latest_snapshot() -> dict | None:
    snap_dir = _REPO_ROOT / SNAPSHOT_DIR
    if not snap_dir.is_dir():
        return None
    snaps = sorted(snap_dir.glob("snapshot-*.json"))
    if not snaps:
        return None
    return json.loads(snaps[-1].read_text(encoding="utf-8"))


# ---------------------------------------------------------------- commands

def cmd_snapshot(vault: str | None) -> int:
    data = snapshot(vault=Path(vault) if vault else None)
    print(f"snapshot saved: {len(data['vault'])} vault nodes, "
          f"{len(data['project'])} project files")
    return 0


def cmd_detect(vault: str | None) -> int:
    before = _load_latest_snapshot()
    if before is None:
        print("no previous snapshot found — run 'snapshot' first")
        return 1
    after = snapshot(vault=Path(vault) if vault else None)
    result = DetectionResult()
    for side in ("vault", "project"):
        b = {k: tuple(v) for k, v in before.get(side, {}).items()}
        a = {k: tuple(v) for k, v in after.get(side, {}).items()}
        result.changes.extend(_diff_snap(b, a, classify))
    # Duplicate-event prevention (req 9): a change key already logged against
    # the SAME baseline is not re-reported.
    seen = _load_logged_keys()
    fresh = [c for c in result.changes if c.dedupe_key not in seen]
    if fresh:
        for c in fresh:
            print(f"{c.kind:<9} [{c.classification:<14}] {c.path}")
        result.changes = fresh
        log_detection(result)
    else:
        print("no new changes detected")
    return 0


def _load_logged_keys() -> set[str]:
    """dedupe keys already recorded in the change log (best-effort)."""
    keys: set[str] = set()
    try:
        path = _REPO_ROOT / CHANGE_LOG
        if not path.is_file():
            return keys
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for c in row.get("changes", []):
                keys.add(f"{c.get('path')}|{c.get('kind')}|{c.get('new_hash') or c.get('old_hash')}")
    except OSError:
        pass
    return keys


def cmd_classify(path: str) -> int:
    print(classify(path))
    return 0


def cmd_affected(vault: str | None, path: str) -> int:
    v = Path(vault) if vault else (_REPO_ROOT / "obsidian_vault")
    nodes = affected_nodes(v, path)
    comps = affected_components(v, path)
    print("affected Obsidian nodes:")
    for n in nodes or ["(none)"]:
        print(f"  - {n}")
    print("linked components:")
    for c in comps or ["(none)"]:
        print(f"  - {c}")
    return 0


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        prog="python -m scripts.core.change_detector",
        description="Detect vault + project changes (snapshot diff).")
    parser.add_argument("--vault", default=None, help="vault path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot", help="write a baseline snapshot")
    sub.add_parser("detect", help="diff against the last snapshot")
    p_classify = sub.add_parser("classify", help="classify a path")
    p_classify.add_argument("path")
    p_affected = sub.add_parser("affected", help="affected nodes/components")
    p_affected.add_argument("path")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            return cmd_snapshot(args.vault)
        if args.command == "detect":
            return cmd_detect(args.vault)
        if args.command == "classify":
            return cmd_classify(args.path)
        if args.command == "affected":
            return cmd_affected(args.vault, args.path)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

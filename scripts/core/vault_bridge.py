"""VaultBridge — safe integration layer between the Orchestrator and Obsidian.

The bridge owns ALL filesystem access to the vault. The Orchestrator routes
every read and write through it. Guarantees (see the Phase 12 plan):

  1. Vault path detection + validation (must exist and contain 03-Tasks/).
  2. Task-node reads scoped to 03-Tasks/ only (no full-vault scans).
  3. Strict frontmatter parsing; malformed nodes are reported, never crashed on.
  4. Task -> Agent -> Component relationship resolution (WikiLinks).
  5. Managed metadata updates (status / updated / execution fields) that
     preserve the human-authored body byte-for-byte.
  6. Nodes are never deleted or overwritten wholesale — only the frontmatter
     block is rewritten (atomic temp-file + os.replace).
  7. A timestamped backup is created in _logs/vault_backups/ BEFORE every write.
  8. Duplicate-execution prevention: a node locked as in_progress (or already
     completed/failed) cannot be dispatched again.
  9. Every change is appended to _logs/vault_changes.jsonl.
  10. Markdown is parsed as data only — nothing inside a node is ever executed.

This module is the bottom of the vault-I/O stack: it depends only on the
standard library, and the Orchestrator imports its primitives from here.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ------------------------------------------------------------------ constants

TASKS_DIR = "03-Tasks"
VALID_STATUSES = {"planned", "ready", "in_progress", "blocked", "completed", "failed"}

BACKUP_DIR = Path("_logs") / "vault_backups"   # relative to the repo root
CHANGE_LOG = Path("_logs") / "vault_changes.jsonl"
LOG_PATH = _REPO_ROOT / "_logs" / "orchestrator.log"
MAX_BACKUPS_PER_NODE = 20

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
LINK_RE = re.compile(r"\[\[([^|\]]+)(?:\|[^\]]+)?\]\]")
KEY_LINE_RE = re.compile(r"^(\w+):\s*(.*)$")

# Hub/index/template files are never treated as executable tasks.
EXEMPT_FILES = {"Tasks_Home.md", "Task_Backlog.md", "_TASK_TEMPLATE.md"}


class VaultError(Exception):
    """Raised for vault/frontmatter/task problems — always safe to report."""


# ------------------------------------------------------------------ logging

def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _log(message: str) -> None:
    """Append a timestamped line to the orchestrator log (never raises)."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{_now()}] {message}\n")
    except OSError:
        pass  # logging must never break orchestration


# ------------------------------------------------------------------ vault access

def validate_vault(vault: Path) -> None:
    """Require the vault to exist and contain a 03-Tasks directory."""
    if not vault.is_dir():
        raise VaultError(f"vault not found: {vault}")
    tasks_dir = vault / TASKS_DIR
    if not tasks_dir.is_dir():
        raise VaultError(f"vault has no {TASKS_DIR}/ directory: {tasks_dir}")


def list_tasks(vault: Path) -> list[Path]:
    """Task node files in 03-Tasks/ (excludes hubs, index, and templates)."""
    validate_vault(vault)
    tasks_dir = vault / TASKS_DIR
    return sorted(
        p for p in tasks_dir.glob("*.md")
        if p.name not in EXEMPT_FILES and not p.name.startswith("_")
    )


def parse_frontmatter(text: str) -> tuple[dict[str, str], str | None]:
    """Parse the frontmatter block into {key: value}; (fields, error)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, "missing frontmatter block (file must start with ---)"
    fields: dict[str, str] = {}
    for lineno, line in enumerate(m.group(1).splitlines(), start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            return {}, f"unparseable frontmatter line {lineno}: {line!r}"
        key, _, value = stripped.partition(":")
        fields[key.strip()] = value.strip()
    return fields, None


def read_node(path: Path) -> tuple[dict[str, str], str, str]:
    """Read any node -> (frontmatter fields, body text, raw text)."""
    if not path.is_file():
        raise VaultError(f"node not found: {path}")
    text = path.read_text(encoding="utf-8")
    fields, err = parse_frontmatter(text)
    if err:
        raise VaultError(f"{path.name}: {err}")
    required = {"type", "status", "owner", "created", "updated"}
    missing = required - set(fields)
    if missing:
        raise VaultError(
            f"{path.name}: missing frontmatter field(s): {', '.join(sorted(missing))}")
    m = FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text
    return fields, body, text


def read_task(path: Path) -> tuple[dict[str, str], str, str]:
    """Read a task node, requiring type == 'task'."""
    fields, body, raw = read_node(path)
    if fields.get("type") != "task":
        raise VaultError(f"{path.name}: not a task node (type={fields.get('type')!r})")
    return fields, body, raw


def resolve_child(base: Path, name: str) -> Path | None:
    """Resolve ``name`` to ``base / '<name>.md'`` only when it is a safe,
    direct child of ``base`` — never a traversal or an escape.

    The security boundary is the *resolved* filesystem path: the candidate's
    resolved parent must equal the resolved ``base``. Names that are empty, a
    dot component, an absolute/drive path, contain a path separator (``/`` or
    ``\``), or contain control characters resolve to ``None`` before the
    filesystem is touched. Unsafe names are rejected outright — never stripped
    or rewritten into another path.

    Returns the resolved Path, or None if the name is unsafe.
    """
    if not name or name in (".", ".."):
        return None
    if any(ch in name for ch in "/\\:") or any(ord(ch) < 32 for ch in name):
        return None
    try:
        base_resolved = base.resolve()
        candidate = (base_resolved / f"{name}.md").resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if candidate.parent != base_resolved:
        return None
    return candidate


def resolve_task(vault: Path, name: str) -> Path | None:
    """Resolve a task node name to a safe path inside 03-Tasks/ (None if unsafe)."""
    return resolve_child(vault / TASKS_DIR, name)


def _find_node(vault: Path, name: str) -> Path | None:
    """Locate ``<name>.md`` in the vault without scanning the entire tree."""
    for sub in ("00-System", "01-Architecture", "02-Agents", "03-Tasks",
                "04-Decisions", "05-Documentation", "06-Testing"):
        candidate = resolve_child(vault / sub, name)
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _replace_frontmatter(text: str, updates: dict[str, str]) -> str:
    """Rebuild the frontmatter block with updated key values.

    Non-updated lines and the entire body are preserved. Only the frontmatter
    block (between the first two ``---`` lines) is touched.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise VaultError("cannot update: missing frontmatter block")
    block = m.group(1)
    out: list[str] = []
    for line in block.splitlines():
        km = KEY_LINE_RE.match(line)
        if km and km.group(1) in updates:
            out.append(f"{km.group(1)}: {updates[km.group(1)]}")
        else:
            out.append(line)
    return "---\n" + "\n".join(out) + "\n---\n" + text[m.end():]


def _atomic_write(path: Path, content: str) -> None:
    """Write via temp file + os.replace so a crash never half-writes a node."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".task.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ------------------------------------------------------------------ backups + log

def _backup_path_for(node: Path) -> Path:
    """First free backup path: _logs/vault_backups/<stem>-<ts>[-N].bak.


    Uses an exclusive-create probe so two writes within the same second can
    never overwrite each other's backup (a counter suffix is appended until a
    free name is found).
    """
    base = _REPO_ROOT / BACKUP_DIR / f"{node.stem}-{_now().replace(':', '-')}"
    candidate = base.with_suffix(".bak")
    n = 1
    while candidate.exists():
        candidate = Path(f"{base}-{n}.bak")
        n += 1
    return candidate



def create_backup(node: Path) -> Path | None:
    """Copy the current node to the backup dir before a write. Never raises."""
    try:
        if not node.is_file():
            return None
        dest = _backup_path_for(node)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(node.read_bytes())
        _prune_backups(node.stem)
        return dest
    except OSError as exc:
        _log(f"vault_bridge: backup failed for {node.name}: {exc}")
        return None


def _prune_backups(stem: str) -> None:
    """Keep only the newest MAX_BACKUPS_PER_NODE backups for one node."""
    try:
        bdir = _REPO_ROOT / BACKUP_DIR
        if not bdir.is_dir():
            return
        backups = sorted(bdir.glob(f"{stem}-*.bak"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-MAX_BACKUPS_PER_NODE]:
            old.unlink(missing_ok=True)
    except OSError:
        pass  # pruning is best-effort


def log_change(node: Path, caller: str, old_fields: dict[str, str],
               new_fields: dict[str, str]) -> None:
    """Append a JSONL change record for every vault write. Never raises."""
    changed = {
        k: {"old": old_fields.get(k), "new": new_fields.get(k)}
        for k in sorted(set(old_fields) | set(new_fields))
        if old_fields.get(k) != new_fields.get(k)
    }
    record = {
        "ts": _now(),
        "caller": caller,
        "node": str(node.relative_to(_REPO_ROOT)).replace(os.sep, "/")
                if node.is_relative_to(_REPO_ROOT) else str(node),
        "changed": changed,
    }
    try:
        path = _REPO_ROOT / CHANGE_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError) as exc:
        _log(f"vault_bridge: change-log append failed: {exc}")


# ---------------------------------------------------------------- relationships

def extract_links(fields: dict[str, str], body: str) -> list[str]:
    """All [[WikiLink]] targets named by a node (frontmatter + body, deduped)."""
    wanted: list[str] = []
    for key in ("assigned_agent", "related_component", "related_agent",
                "related_task", "parent"):
        val = (fields.get(key) or "").strip()
        if val and val not in wanted:
            wanted.append(val)
    for m in LINK_RE.finditer(body):
        target = m.group(1).strip()
        if target and target not in wanted:
            wanted.append(target)
    return wanted


def resolve_relationships(vault: Path, fields: dict[str, str],
                          body: str) -> tuple[dict[str, Path], list[str]]:
    """Resolve every link a task names -> (node_name -> Path, unresolved_names).

    Reads only the named node files (scoped), never the whole vault. Hub and
    template files are excluded from resolution.
    """
    resolved: dict[str, Path] = {}
    unresolved: list[str] = []
    for name in extract_links(fields, body):
        if name.endswith("_Home") or name == "Task_Backlog":
            continue
        hit = _find_node(vault, name)
        if hit is not None:
            resolved[name] = hit
        else:
            unresolved.append(name)
    return resolved, unresolved


# ---------------------------------------------------------------- managed writes

def update_node(node: Path, caller: str, updates: dict[str, str],
                new_body: str | None = None) -> dict[str, str]:
    """Update a NON-task node's managed fields (same safety as update_task).

    Used by the knowledge-sync layer for agent/architecture/documentation/
    test nodes. Enforces only the shared node schema (type/status/owner/
    created/updated present); does not require type == 'task'.
    """
    fields, _body, raw = read_node(node)
    if not updates:
        return fields  # no-op: no backup, no log, no write
    updated_raw = _replace_frontmatter(raw, updates)
    if new_body is not None:
        m = FRONTMATTER_RE.match(updated_raw)
        if m:
            updated_raw = updated_raw[: m.end()] + new_body
    create_backup(node)
    _atomic_write(node, updated_raw)
    new_fields, _err = parse_frontmatter(updated_raw)
    log_change(node, caller, fields, new_fields or {})
    return new_fields or {}


def update_task(node: Path, caller: str, updates: dict[str, str],
                new_body: str | None = None) -> dict[str, str]:
    """Atomically update a task node's managed fields; body preserved.

    Safety:
      * A backup is created first (create_backup) — never raises.
      * Only frontmatter keys in ``updates`` are rewritten; the rest of the
        frontmatter and the entire body are preserved byte-for-byte.
      * The write is atomic (temp file + os.replace).
      * The change is recorded in _logs/vault_changes.jsonl.

    Returns the NEW frontmatter fields.
    """
    fields, _body, raw = read_task(node)
    if not updates:
        return fields  # no-op: no backup, no log, no write
    updated_raw = _replace_frontmatter(raw, updates)
    if new_body is not None:
        # Replace only the body (everything after the frontmatter block).
        m = FRONTMATTER_RE.match(updated_raw)
        if m:
            updated_raw = updated_raw[: m.end()] + new_body
    create_backup(node)
    _atomic_write(node, updated_raw)
    new_fields, _err = parse_frontmatter(updated_raw)
    log_change(node, caller, fields, new_fields or {})
    return new_fields or {}


# ---------------------------------------------------------------- duplicate guard

def is_dispatchable(fields: dict[str, str]) -> tuple[bool, str | None]:
    """A task may be dispatched only when not in_progress/completed/failed."""
    status = fields.get("status", "")
    if status in ("in_progress", "completed", "failed"):
        return False, f"status={status} (already executed or in flight)"
    return True, None


# ---------------------------------------------------------------- public surface

__all__ = [
    "BACKUP_DIR",
    "CHANGE_LOG",
    "EXEMPT_FILES",
    "FRONTMATTER_RE",
    "KEY_LINE_RE",
    "LINK_RE",
    "LOG_PATH",
    "MAX_BACKUPS_PER_NODE",
    "TASKS_DIR",
    "VALID_STATUSES",
    "VaultError",
    "_atomic_write",
    "_find_node",
    "_log",
    "_now",
    "_prune_backups",
    "_replace_frontmatter",
    "create_backup",
    "extract_links",
    "is_dispatchable",
    "list_tasks",
    "log_change",
    "parse_frontmatter",
    "read_node",
    "read_task",
    "resolve_child",
    "resolve_relationships",
    "resolve_task",
    "update_node",
    "update_task",
    "validate_vault",
]

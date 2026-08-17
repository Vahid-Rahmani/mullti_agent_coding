"""KnowledgeSync — reconcile the codebase with the Obsidian knowledge graph.

Sources of truth (Phase 16):
  * CODE is the truth for implementation — sync NEVER edits source code.
  * OBSIDIAN is the truth for architecture/tasks/decisions/knowledge — sync
    edits ONLY managed fields and generated marker blocks.

Design:
  * `sync` is DRY-RUN by default: it computes the plan and prints it, writing
    nothing. Pass `--apply` to execute (vault managed sections only).
  * Managed fields: `updated` (date), `status` (task lifecycle), and
    `related_component` (only when the component node + code path both exist).
  * Generated sections: only blocks between `<!-- GENERATED: <key> -->` and
    `<!-- /GENERATED -->` markers may be rewritten. Everything else is
    preserved byte-for-byte (via the vault bridge).
  * No false documentation: links are added only for what exists.
  * `check-conflicts` compares documented architecture against the real
    codebase and REPORTS drift — it never changes either side.
  * Every run appends one JSONL row to _logs/sync_log.jsonl.

CLI:

    python -m scripts.core.knowledge_sync sync [--apply] [--vault P]
    python -m scripts.core.knowledge_sync check-conflicts [--vault P]
    python -m scripts.core.knowledge_sync log
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SYNC_LOG = Path("_logs") / "sync_log.jsonl"

from scripts.core.vault_bridge import (
    VaultError,
    _log,
    _now,
    read_node,
    update_node,
    validate_vault,
)

# Managed fields the sync is allowed to touch (human content is off-limits).
MANAGED_FIELDS = ("updated", "status", "related_component")
GENERATED_OPEN = re.compile(r"<!-- GENERATED: ([a-z0-9_-]+) -->\s*\n")
GENERATED_CLOSE = re.compile(r"<!-- /GENERATED -->\s*")


@dataclass
class SyncAction:
    node: str          # vault-relative path, e.g. 01-Architecture/Component_X.md
    field: str         # 'updated' | 'status' | 'related_component' | 'generated:<key>'
    old: str = ""
    new: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class SyncPlan:
    actions: list[SyncAction] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.actions and not self.conflicts


# ---------------------------------------------------------------- vault scan

def _all_vault_nodes(vault: Path) -> list[Path]:
    nodes: list[Path] = []
    for section in ("00-System", "01-Architecture", "02-Agents", "03-Tasks",
                    "04-Decisions", "05-Documentation", "06-Testing"):
        folder = vault / section
        if folder.is_dir():
            nodes.extend(sorted(folder.glob("*.md")))
    return [p for p in nodes if not p.name.startswith("_")]


# ---------------------------------------------------------------- impact mapping

def component_stem_to_tokens(rel_path: str) -> set[str]:
    """tokens used to link a code path to Component_* nodes."""
    stem = Path(rel_path).stem
    snake = re.sub(r"[_-]+", "_", stem)
    camel = "".join(part[:1].upper() + part[1:] for part in snake.split("_"))
    return {snake, stem, camel, f"Component_{camel}"}


def find_component_node(vault: Path, code_rel: str) -> Path | None:
    """The Component_* node whose stem matches the code path, if any."""
    tokens = component_stem_to_tokens(code_rel)
    for section in ("01-Architecture",):
        folder = vault / section
        if not folder.is_dir():
            continue
        for node_file in sorted(folder.glob("Component_*.md")):
            if node_file.stem in tokens or node_file.stem[10:] in tokens:
                return node_file
    return None


# ---------------------------------------------------------------- plan building

def build_plan(vault: Path) -> SyncPlan:
    """Dry-run plan: what sync WOULD change (computed, nothing written)."""
    plan = SyncPlan()
    today = _now()[:10]

    for node_path in _all_vault_nodes(vault):
        try:
            fields, body, _raw = read_node(node_path)
        except VaultError:
            continue  # malformed nodes are reported by the validator, not us
        rel = node_path.relative_to(vault)

        # 1. Node type by section (for managed-status semantics).
        section = rel.parts[0] if rel.parts else ""

        # 2. `updated` managed field -> today, when stale.
        if fields.get("updated") != today:
            plan.actions.append(SyncAction(
                node=str(rel).replace(os.sep, "/"), field="updated",
                old=fields.get("updated", ""), new=today))

        # 3. related_component managed field: add ONLY when the referenced
        #    component node exists AND its backing code path exists.
        rc = (fields.get("related_component") or "").strip()
        if rc and rc.startswith("Component_"):
            comp_node = vault / "01-Architecture" / f"{rc}.md"
            if not comp_node.is_file():
                plan.conflicts.append(
                    f"{rel}: related_component {rc} has no node in 01-Architecture/")

        # 4. Task status lifecycle: only for actual task nodes (hubs/index
        #    files carry the section's shared schema, not task statuses).
        name = node_path.stem
        is_hub = name.endswith(("_Home", "_Index")) or name in ("Task_Backlog",)
        if section == "03-Tasks" and not is_hub:
            status = fields.get("status", "")
            if status not in ("planned", "ready", "in_progress", "blocked",
                              "completed", "failed"):
                plan.conflicts.append(f"{rel}: invalid task status {status!r}")

        # 5. Generated blocks: flag stale generated content? (read-only here)
        for m in GENERATED_OPEN.finditer(body):
            key = m.group(1)
            close = GENERATED_CLOSE.search(body[m.end():])
            if close is None:
                plan.conflicts.append(
                    f"{rel}: generated block '{key}' has no closing marker")
    return plan


# ---------------------------------------------------------------- conflict checks

def check_conflicts(vault: Path) -> list[str]:
    """Documented architecture vs actual codebase drift — REPORT ONLY."""
    conflicts: list[str] = []

    # A) Component nodes claiming source paths that don't exist.
    for node_file in (vault / "01-Architecture").glob("Component_*.md"):
        try:
            text = node_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"(?:`([\w/.-]+\.(?:py|js|ts|ps1|bat|sh|json|md))`)", text):
            path = m.group(1)
            if not (_REPO_ROOT / path).exists():
                conflicts.append(
                    f"{node_file.stem}: documents {path!r} but it does not exist in the repo")

    # B) Real code modules with no Component_* node (undocumented).
    code_modules = sorted(
        p for p in (_REPO_ROOT / "scripts" / "core").glob("*.py")
        if p.name not in ("__init__.py", "progress.py", "state_tracker.py")
        and p.name not in ("command_parser.py",)
    )
    known = {n.stem for n in (vault / "01-Architecture").glob("Component_*.md")}
    known |= {"System_Architecture"}
    for module in code_modules:
        if not find_component_node(vault, module.name) and module.stem not in known:
            conflicts.append(
                f"{module.name}: real module with no Component_* node in the vault map")

    # C) Generated-block integrity (from the plan).
    plan = build_plan(vault)
    conflicts.extend(plan.conflicts)
    return sorted(set(conflicts))


# ---------------------------------------------------------------- apply

def _set_generated_section(body: str, key: str, content: str) -> str:
    """Replace/insert a generated block; everything else preserved."""
    open_marker = f"<!-- GENERATED: {key} -->"
    close_marker = "<!-- /GENERATED -->"
    block = f"{open_marker}\n{content.rstrip()}\n{close_marker}"
    pattern = re.compile(
        rf"{re.escape(open_marker)}.*?{re.escape(close_marker)}", re.DOTALL)
    if pattern.search(body):
        return pattern.sub(lambda _m: block, body, count=1)
    trimmed = body.rstrip()
    return trimmed + ("\n\n" if trimmed else "") + block + "\n"


def apply_plan(vault: Path, plan: SyncPlan) -> int:
    """Execute a plan against the vault — managed fields + generated blocks ONLY."""
    applied = 0
    for action in plan.actions:
        if action.field == "generated:":
            continue  # generated-section content is set by dedicated syncs
        node_path = vault / action.node.replace("/", os.sep)
        if not node_path.is_file():
            continue
        if action.field in MANAGED_FIELDS:
            try:
                update_node(node_path, "knowledge-sync",
                            {action.field: action.new})
                applied += 1
            except VaultError as exc:
                _log(f"knowledge_sync: skip {action.node}: {exc}")
    return applied


# ---------------------------------------------------------------- logging

def log_run(mode: str, plan: SyncPlan, dry_run: bool) -> None:
    record = {
        "ts": _now(),
        "mode": mode,
        "dry_run": dry_run,
        "actions": [a.to_dict() for a in plan.actions],
        "conflicts": plan.conflicts,
    }
    try:
        path = _REPO_ROOT / SYNC_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError):
        pass


# ---------------------------------------------------------------- CLI

def cmd_sync(vault: Path, apply: bool) -> int:
    plan = build_plan(vault)
    if plan.actions:
        print(f"sync plan: {len(plan.actions)} action(s)"
              + ("" if apply else "  (DRY-RUN — pass --apply to execute)"))
        for a in plan.actions[:20]:
            print(f"  {a.node}: {a.field} {a.old!r} -> {a.new!r}")
        if len(plan.actions) > 20:
            print(f"  ... and {len(plan.actions) - 20} more")
    if plan.conflicts:
        print(f"conflicts: {len(plan.conflicts)}")
        for c in plan.conflicts[:20]:
            print(f"  ! {c}")
    if apply and plan.actions:
        n = apply_plan(vault, plan)
        print(f"applied {n} managed update(s)")
    log_run("sync", plan, dry_run=not apply)
    return 0


def cmd_check_conflicts(vault: Path) -> int:
    conflicts = check_conflicts(vault)
    plan = SyncPlan(conflicts=conflicts)
    if conflicts:
        print(f"CONFLICTS: {len(conflicts)}")
        for c in conflicts:
            print(f"  ! {c}")
    else:
        print("no conflicts — documented architecture matches the codebase")
    log_run("check-conflicts", plan, dry_run=True)
    return 1 if conflicts else 0


def cmd_log() -> int:
    path = _REPO_ROOT / SYNC_LOG
    if not path.is_file():
        print("no sync log yet")
        return 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for r in rows[-10:]:
        print(f"{r['ts']} {r['mode']:<16} dry={r['dry_run']} "
              f"actions={len(r['actions'])} conflicts={len(r['conflicts'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        prog="python -m scripts.core.knowledge_sync",
        description="Reconcile code with the Obsidian knowledge graph.")
    sub = parser.add_subparsers(dest="command", required=True)
    vault_parent = argparse.ArgumentParser(add_help=False)
    vault_parent.add_argument("--vault", dest="vault_sub", default=None, help="vault path")
    p_sync = sub.add_parser("sync", parents=[vault_parent],
                            help="compute (and with --apply, execute) the sync plan")
    p_sync.add_argument("--apply", action="store_true", help="apply managed updates")
    sub.add_parser("check-conflicts", parents=[vault_parent],
                   help="report architecture/code drift")
    sub.add_parser("log", parents=[vault_parent], help="show recent sync events")
    args = parser.parse_args(argv)
    try:
        vault_arg = getattr(args, "vault_sub", None)
        vault = Path(vault_arg) if vault_arg else (_REPO_ROOT / "obsidian_vault")
        validate_vault(vault)
        if args.command == "sync":
            return cmd_sync(vault, args.apply)
        if args.command == "check-conflicts":
            return cmd_check_conflicts(vault)
        if args.command == "log":
            return cmd_log()
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

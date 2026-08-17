"""Vault validator — enforce the Phase 04 node schema on obsidian_vault/.

Checks, per Markdown node under ``obsidian_vault/``:
  * frontmatter present and parseable (YAML subset)
  * required fields: type, status, owner, created, updated
  * ``type`` is one of the 7 supported values and matches its section folder
  * ``status`` is allowed for the node's type
  * ``created`` / ``updated`` look like ISO dates (YYYY-MM-DD)
  * every ``related`` entry resolves to an existing node name
  * no duplicate node names vault-wide
  * every non-root node has an ``↑ Parent:`` link in its body
  * no orphan nodes (no inbound links)

Legacy vault files (``Dashboard.md``, ``Roadmap.md``, ``prompts/``,
``agents_logs/``) are exempt: they predate the schema and are intentionally
left unchanged.

Usage:
    python scripts/vault_validate.py [--vault <path>]

Exit codes:
    0  all checks pass
    1  one or more violations (listed on stdout)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.core.vault_bridge import parse_frontmatter

DEFAULT_VAULT = REPO_ROOT / "obsidian_vault"

TYPE_SECTIONS = {
    "system": "00-System",
    "architecture": "01-Architecture",
    "agent": "02-Agents",
    "task": "03-Tasks",
    "decision": "04-Decisions",
    "documentation": "05-Documentation",
    "test": "06-Testing",
}

ALLOWED_STATUS = {
    "system": {"active", "draft"},
    "architecture": {"active", "draft", "superseded"},
    "agent": {"active", "retired"},
    # Hub/index nodes use active/draft; leaf task nodes use the orchestrator's
    # execution vocabulary (the same set scripts/core/vault_bridge.py and the
    # Orchestrator's TRANSITIONS enforce). planned/ready → in_progress →
    # completed|blocked|failed. The legacy todo/done aliases were removed to
    # keep one source of truth for task state.
    "task": {"active", "draft", "planned", "ready", "in_progress", "blocked",
            "completed", "failed"},
    "decision": {"active", "draft", "proposed", "accepted", "superseded"},
    "documentation": {"active", "draft"},
    "test": {"active", "draft", "passed", "failed", "blocked"},
}

VALID_OWNERS = {
    "matthew", "alex", "sarah", "david", "elena", "max", "chloe",
    "architect", "orchestrator", "testing", "all",
}

VALID_PRIORITIES = {"low", "medium", "high", "critical"}

# Extra frontmatter keys allowed per type (validated when present).
EXTRA_KEYS = {
    "task": {"priority", "assigned_agent", "related_component", "dependencies"},
    "test": {"related_component", "related_agent", "related_task", "test_command"},
}

ROOT_NODE = "System_Core"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"\[\[([^|\]]+)(?:\|[^\]]+)?\]\]")

# Frontmatter keys the vault schema recognizes. Parsing itself is delegated to
# the canonical ``scripts.core.vault_bridge.parse_frontmatter`` (which accepts
# any flat ``key: value`` line); this allowlist is the validator's schema
# check, kept separate from the shared parser.
KNOWN_FRONTMATTER_KEYS = {
    "type", "status", "owner", "created", "updated", "related",
    "priority", "assigned_agent", "related_component", "dependencies",
    "related_agent", "related_task", "test_command", "role",
}


def _strip_code(text: str) -> str:
    """Remove fenced + inline code so example links are not counted."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`]*`", "", text)


def list_nodes(vault: Path) -> list[Path]:
    """All schema-managed node files (00-06 folders only).

    ``_``-prefixed files (e.g. ``_TASK_TEMPLATE.md``) are templates and are
    exempt from schema checks (they intentionally hold placeholders).
    """
    nodes: list[Path] = []
    for section in TYPE_SECTIONS.values():
        section_dir = vault / section
        if section_dir.is_dir():
            for path in sorted(section_dir.glob("*.md")):
                if path.name.startswith("_"):
                    continue
                nodes.append(path)
    return nodes


def collect_links(nodes: list[Path]) -> set[str]:
    """All real (non-code) [[targets]] across the managed nodes."""
    targets: set[str] = set()
    for path in nodes:
        text = _strip_code(path.read_text(encoding="utf-8"))
        for m in LINK_RE.finditer(text):
            targets.add(m.group(1).strip())
    return targets


def main(argv: list[str] | None = None) -> int:
    # Console-safe output on legacy Windows codepages (cp1252 can't print ↑).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", default=str(DEFAULT_VAULT), help="vault root (default: repo obsidian_vault)")
    args = parser.parse_args(argv)

    vault = Path(args.vault).resolve()
    nodes = list_nodes(vault)
    node_names = {path.stem for path in nodes}
    violations: list[str] = []

    if not nodes:
        violations.append(f"no schema-managed nodes found under {vault}")
    else:
        # Unique-name check + frontmatter + field + type/section + status checks.
        seen: dict[str, Path] = {}
        for path in nodes:
            if path.stem in seen:
                violations.append(f"duplicate node name: {path.stem} ({path} and {seen[path.stem]})")
            seen[path.stem] = path

            text = path.read_text(encoding="utf-8")
            fields, err = parse_frontmatter(text)
            if err:
                violations.append(f"{path}: {err}")
                continue

            unknown = sorted(k for k in fields if k not in KNOWN_FRONTMATTER_KEYS)
            if unknown:
                violations.append(f"{path}: unknown frontmatter key(s): {', '.join(unknown)}")
                continue

            missing = [k for k in ("type", "status", "owner", "created", "updated") if k not in fields]
            if missing:
                violations.append(f"{path}: missing frontmatter field(s): {', '.join(missing)}")
                continue

            ntype = fields["type"]
            if ntype not in TYPE_SECTIONS:
                violations.append(f"{path}: unknown type {ntype!r}")
                continue
            section = TYPE_SECTIONS[ntype]
            if section not in str(path):
                violations.append(f"{path}: type {ntype!r} does not match its section folder ({section}/)")

            status = fields["status"]
            if status not in ALLOWED_STATUS[ntype]:
                allowed = ", ".join(sorted(ALLOWED_STATUS[ntype]))
                violations.append(f"{path}: status {status!r} not allowed for type {ntype!r} (allowed: {allowed})")

            owner = fields["owner"]
            if owner not in VALID_OWNERS:
                violations.append(f"{path}: owner {owner!r} not in valid owners: {', '.join(sorted(VALID_OWNERS))}")

            for field in ("created", "updated"):
                if not DATE_RE.match(fields[field]):
                    violations.append(f"{path}: {field} {fields[field]!r} is not YYYY-MM-DD")

            related_raw = fields.get("related", "").strip("[] ")
            for name in [n.strip() for n in related_raw.split(",") if n.strip()]:
                if name not in node_names:
                    violations.append(f"{path}: related [{name}] does not resolve to a node")

            # Task-specific optional fields (validated when present).
            priority = fields.get("priority", "")
            if priority and priority not in VALID_PRIORITIES:
                violations.append(f"{path}: priority {priority!r} not in {sorted(VALID_PRIORITIES)}")
            for field in ("assigned_agent", "related_component"):
                val = fields.get(field, "")
                if val and val not in node_names:
                    violations.append(f"{path}: {field} [{val}] does not resolve to a node")
            deps_raw = fields.get("dependencies", "").strip("[] ")
            for name in [n.strip() for n in deps_raw.split(",") if n.strip()]:
                if name not in node_names:
                    violations.append(f"{path}: dependencies [{name}] does not resolve to a node")

            # Test-report optional fields (validated when present).
            for field in ("related_agent", "related_task"):
                val = fields.get(field, "")
                if val and val not in node_names:
                    violations.append(f"{path}: {field} [{val}] does not resolve to a node")

        # Parent-link check: every node except the root has '↑ Parent:'.
        for path in nodes:
            if path.stem == ROOT_NODE:
                continue
            text = _strip_code(path.read_text(encoding="utf-8"))
            if "↑ Parent:" not in text:
                violations.append(f"{path}: missing '↑ Parent:' link")

        # Orphan check: every node must have at least one inbound real link.
        inbound = collect_links(nodes)
        for path in nodes:
            if path.stem not in inbound:
                violations.append(f"{path}: orphan node (no inbound links)")

    if violations:
        print(f"VAULT VALIDATION FAILED — {len(violations)} issue(s):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(f"VAULT VALIDATION OK — {len(nodes)} node(s), all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

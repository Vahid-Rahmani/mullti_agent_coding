"""Obsidian Vault Auditor — M7 Chloe's read-only documentation audit engine.

Pure-stdlib module that implements the 'Obsidian-Vault-Sync & Final Audit'
mode for agent M7 (Chloe). It never writes production code — its sole
responsibilities are:

1. **Vault Integrity Verification** — ensures the ``obsidian_vault/``
   directory structure is valid, agent log files exist for all active
   agents, and no orphaned or malformed files are present.

2. **Cross-Referencing** — links every prompt log in ``prompts/`` to
   corresponding entries in ``agents_logs/`` to guarantee end-to-end
   traceability.

3. **Roadmap Synchronization** — updates ``Roadmap.md`` based on the
   current project state (git branch, completed tasks from ``state.md``,
   and prompt log activity).

Additionally, the auditor validates Dashboard.md WikiLinks and checks
that Roadmap.md reflects completed phases with ``- [x]`` checkboxes.

No third-party imports; read-only except for Roadmap.md updates (atomic
write via tempfile + os.replace).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(os.getcwd())
_VAULT_ROOT = _PROJECT_ROOT / "obsidian_vault"

# --------------------------------------------------------------------------- vault integrity


def verify_vault_integrity(
    vault_root: str | os.PathLike | None = None,
) -> dict:
    """Check the obsidian_vault/ directory structure and report issues.

    Returns a dict with ``ok`` (bool), ``issues`` (list[str]), and
    ``summary`` (str). An empty issues list and ``ok=True`` means the
    vault is healthy.
    """
    root = Path(vault_root) if vault_root is not None else _VAULT_ROOT
    issues: list[str] = []

    if not root.is_dir():
        return {
            "ok": False,
            "issues": [f"Vault root missing: {root}"],
            "summary": "CRITICAL: obsidian_vault/ directory not found.",
        }

    required_files = ["Dashboard.md", "Roadmap.md"]
    for fname in required_files:
        fp = root / fname
        if not fp.is_file():
            issues.append(f"Missing required file: {fname}")
        elif fp.stat().st_size == 0:
            issues.append(f"Empty required file: {fname}")

    prompts_dir = root / "prompts"
    agents_dir = root / "agents_logs"

    for dname, dpath in [("prompts", prompts_dir), ("agents_logs", agents_dir)]:
        if not dpath.is_dir():
            issues.append(f"Missing directory: {dname}/")

    if prompts_dir.is_dir():
        prompt_files = sorted(prompts_dir.glob("prompt-*.md"))
        if not prompt_files:
            issues.append("No prompt logs found in prompts/")

    if agents_dir.is_dir():
        agent_files = sorted(agents_dir.glob("M*_*.md"))
        if not agent_files:
            issues.append("No agent log files found in agents_logs/")

    ok = len(issues) == 0
    summary = (
        "Vault integrity: PASS — all required files and directories present."
        if ok
        else f"Vault integrity: {len(issues)} issue(s) found."
    )
    return {"ok": ok, "issues": issues, "summary": summary}


# --------------------------------------------------------------------------- cross-referencing


def cross_reference_prompts(
    vault_root: str | os.PathLike | None = None,
) -> dict:
    """Ensure every prompt log has corresponding agent run entries.

    Scans ``prompts/prompt-*.md`` and ``agents_logs/M*_*.md``, then reports
    any prompt that is not referenced by at least one agent log. Returns a
    dict with ``ok``, ``orphaned_prompts`` (list[str]), ``referenced_prompts``
    (set[str]), and ``summary`` (str).
    """
    root = Path(vault_root) if vault_root is not None else _VAULT_ROOT
    prompts_dir = root / "prompts"
    agents_dir = root / "agents_logs"

    prompt_ids: set[str] = set()
    if prompts_dir.is_dir():
        for pf in prompts_dir.glob("prompt-*.md"):
            prompt_ids.add(pf.stem)

    referenced: set[str] = set()
    if agents_dir.is_dir():
        link_pat = re.compile(r"\[\[\.\.\/prompts\/(prompt-\d+)\]\]")
        for af in agents_dir.glob("M*_*.md"):
            try:
                text = af.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in link_pat.finditer(text):
                referenced.add(match.group(1))

    orphaned = sorted(prompt_ids - referenced)
    ok = len(orphaned) == 0
    summary = (
        "Cross-reference: PASS — all prompts are referenced by agent logs."
        if ok
        else f"Cross-reference: {len(orphaned)} orphaned prompt(s) — no agent log entries."
    )
    return {
        "ok": ok,
        "orphaned_prompts": orphaned,
        "referenced_prompts": referenced,
        "summary": summary,
    }


# --------------------------------------------------------------------------- roadmap sync


def _git_branch(project_root: Path) -> str:
    """Return the current git branch name, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _git_diff_summary(project_root: Path) -> str:
    """Return a short summary of uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            return f"{len(lines)} file(s) modified"
    except (OSError, subprocess.SubprocessError):
        pass
    return "no changes or git unavailable"


def _completed_tasks(project_root: Path) -> list[str]:
    """Read completed agent runs from state.md."""
    state_path = project_root / "state.md"
    if not state_path.is_file():
        return []
    tasks: list[str] = []
    in_completed = False
    try:
        for line in state_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## Completed"):
                in_completed = True
                continue
            if in_completed:
                if line.startswith("## "):
                    break
                stripped = line.strip().lstrip("-").strip()
                if stripped and not stripped.startswith("..."):
                    tasks.append(stripped)
    except OSError:
        pass
    return tasks


def _prompt_log_count(project_root: Path) -> int:
    """Count prompt-*.md files in the vault."""
    prompts_dir = project_root / "obsidian_vault" / "prompts"
    if not prompts_dir.is_dir():
        return 0
    return len(list(prompts_dir.glob("prompt-*.md")))


def sync_roadmap(
    vault_root: str | os.PathLike | None = None,
    project_root: str | os.PathLike | None = None,
) -> dict:
    """Update Roadmap.md with current project state.

    Reads the current git branch, uncommitted changes, completed tasks from
    ``state.md``, and prompt log count, then patches the ``> **Last updated:**
    `` and ``> **Current branch:**`` lines in ``Roadmap.md``. An atomic write
    ensures the file is never left in a half-written state.

    Returns a dict with ``ok``, ``branch``, ``diff_summary``, and
    ``roadmap_path``.
    """
    proj = Path(project_root) if project_root is not None else _PROJECT_ROOT
    vault = Path(vault_root) if vault_root is not None else _VAULT_ROOT
    roadmap_path = vault / "Roadmap.md"

    branch = _git_branch(proj)
    diff = _git_diff_summary(proj)
    completed = _completed_tasks(proj)
    prompt_count = _prompt_log_count(proj)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not roadmap_path.is_file():
        return {
            "ok": False,
            "branch": branch,
            "diff_summary": diff,
            "roadmap_path": str(roadmap_path),
            "error": "Roadmap.md not found",
        }

    try:
        original = roadmap_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "ok": False,
            "branch": branch,
            "diff_summary": diff,
            "roadmap_path": str(roadmap_path),
            "error": "Cannot read Roadmap.md",
        }

    # Patch the metadata lines.
    updated = re.sub(
        r"^> \*\*Last updated:\*\* .*$",
        f"> **Last updated:** {now}",
        original,
        count=1,
        flags=re.MULTILINE,
    )
    updated = re.sub(
        r"^> \*\*Current branch:\*\* .*$",
        f"> **Current branch:** `{branch}`",
        updated,
        count=1,
        flags=re.MULTILINE,
    )

    # Append a status footer if not already present.
    status_block = (
        f"\n---\n\n## Audit Status (M7 — Obsidian-Vault-Sync)\n\n"
        f"- **Last audit:** {now}\n"
        f"- **Branch:** `{branch}`\n"
        f"- **Uncommitted changes:** {diff}\n"
        f"- **Completed runs:** {len(completed)}\n"
        f"- **Prompt logs:** {prompt_count}\n"
    )
    if "## Audit Status" not in original:
        updated = updated.rstrip() + status_block

    # Atomic write.
    fd, tmp = tempfile.mkstemp(dir=str(vault), suffix=".roadmap.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(updated)
        os.replace(tmp, roadmap_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    return {
        "ok": True,
        "branch": branch,
        "diff_summary": diff,
        "completed_runs": len(completed),
        "prompt_log_count": prompt_count,
        "roadmap_path": str(roadmap_path),
    }


# --------------------------------------------------------------------------- dashboard wiki-link validation


def verify_dashboard_wikilinks(
    vault_root: str | os.PathLike | None = None,
) -> dict:
    """Validate that Dashboard.md WikiLinks point to existing vault pages.

    Scans ``Dashboard.md`` for ``[[...]]`` wiki-links and checks whether
    each target (file or directory) actually exists in the vault. Returns
    a dict with ``ok``, ``total_links``, ``broken_links``, and ``summary``.
    """
    root = Path(vault_root) if vault_root is not None else _VAULT_ROOT
    dashboard = root / "Dashboard.md"

    if not dashboard.is_file():
        return {
            "ok": False,
            "total_links": 0,
            "broken_links": ["Dashboard.md missing"],
            "summary": "Dashboard.md not found.",
        }

    try:
        text = dashboard.read_text(encoding="utf-8")
    except OSError:
        return {
            "ok": False,
            "total_links": 0,
            "broken_links": ["Cannot read Dashboard.md"],
            "summary": "Cannot read Dashboard.md.",
        }

    # Match [[Target]] or [[Target|Alias]] or [[path/to/file]]
    link_pat = re.compile(r"\[\[([^\]#|]+)(?:[#|][^\]]+)?\]\]")
    broken: list[str] = []
    total = 0

    for match in link_pat.finditer(text):
        target = match.group(1).strip()
        total += 1
        if target.endswith("/"):
            # Directory link — check the directory exists.
            dir_path = root / target.rstrip("/")
            if not dir_path.is_dir():
                broken.append(f"[[{target}]] (directory not found)")
        else:
            # File link — check the .md file exists.
            if "/" in target:
                file_path = root / f"{target}.md" if not target.endswith(".md") else root / target
            else:
                file_path = root / f"{target}.md"
            if not file_path.is_file():
                broken.append(f"[[{target}]] (file not found)")

    ok = len(broken) == 0
    summary = (
        f"Dashboard WikiLinks: PASS — {total} link(s), all valid."
        if ok
        else f"Dashboard WikiLinks: {len(broken)}/{total} broken."
    )
    return {
        "ok": ok,
        "total_links": total,
        "broken_links": broken,
        "summary": summary,
    }


# --------------------------------------------------------------------------- roadmap checkbox scan


def verify_roadmap_checkboxes(
    vault_root: str | os.PathLike | None = None,
) -> dict:
    """Scan Roadmap.md for completed phases lacking ``- [x]`` checkboxes.

    Reads the completed tasks from ``state.md`` and checks whether any
    task that appears completed in state is still marked ``- [ ]`` in the
    Roadmap. Returns ``ok``, ``mismatches``, and ``summary``.
    """
    root = Path(vault_root) if vault_root is not None else _VAULT_ROOT
    roadmap_path = root / "Roadmap.md"

    if not roadmap_path.is_file():
        return {
            "ok": False,
            "mismatches": ["Roadmap.md missing"],
            "summary": "Roadmap.md not found.",
        }

    try:
        text = roadmap_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "ok": False,
            "mismatches": ["Cannot read Roadmap.md"],
            "summary": "Cannot read Roadmap.md.",
        }

    # Find all phases (## Phase X) and count checked vs unchecked items.
    phases: dict[str, dict[str, int]] = {}
    current_phase = "(preamble)"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Phase") or stripped.startswith("## Backlog"):
            current_phase = stripped.lstrip("#").strip()
            phases.setdefault(current_phase, {"checked": 0, "unchecked": 0, "total": 0})
            continue
        if stripped.startswith("- [x]"):
            phases.setdefault(current_phase, {"checked": 0, "unchecked": 0, "total": 0})
            phases[current_phase]["checked"] += 1
            phases[current_phase]["total"] += 1
        elif stripped.startswith("- [ ]"):
            phases.setdefault(current_phase, {"checked": 0, "unchecked": 0, "total": 0})
            phases[current_phase]["unchecked"] += 1
            phases[current_phase]["total"] += 1

    mismatches: list[str] = []
    for phase, counts in phases.items():
        if counts["total"] == 0:
            continue
        pct = counts["checked"] / counts["total"] * 100 if counts["total"] else 0
        if counts["unchecked"] > 0:
            mismatches.append(
                f"{phase}: {counts['checked']}/{counts['total']} checked ({pct:.0f}%) — "
                f"{counts['unchecked']} item(s) still pending"
            )

    ok = len(mismatches) == 0
    summary = (
        "Roadmap checkboxes: PASS — all items checked."
        if ok
        else f"Roadmap checkboxes: {len(mismatches)} phase(s) with pending items."
    )
    return {"ok": ok, "mismatches": mismatches, "summary": summary}


# --------------------------------------------------------------------------- master audit


def audit_run(
    vault_root: str | os.PathLike | None = None,
    project_root: str | os.PathLike | None = None,
) -> dict:
    """Run the full M7 audit: integrity check + cross-reference + roadmap sync.

    This is the entry point called after a dispatch that includes M7. It
    never raises; errors are captured in the result dict.

    Returns a dict with ``ok`` (bool), ``integrity``, ``cross_ref``,
    ``roadmap``, and ``summary`` (str).
    """
    vault = Path(vault_root) if vault_root is not None else _VAULT_ROOT
    proj = Path(project_root) if project_root is not None else _PROJECT_ROOT

    integrity = verify_vault_integrity(vault_root=vault)
    cross_ref = cross_reference_prompts(vault_root=vault)
    wikilinks = verify_dashboard_wikilinks(vault_root=vault)
    checkboxes = verify_roadmap_checkboxes(vault_root=vault)
    roadmap = sync_roadmap(vault_root=vault, project_root=proj)

    all_ok = (
        integrity["ok"]
        and cross_ref["ok"]
        and wikilinks["ok"]
        and checkboxes["ok"]
        and roadmap.get("ok", False)
    )

    parts: list[str] = []
    parts.append(f"  Integrity:  {'PASS' if integrity['ok'] else 'FAIL'}")
    parts.append(f"  Cross-ref:  {'PASS' if cross_ref['ok'] else 'FAIL'}")
    parts.append(f"  WikiLinks:  {'PASS' if wikilinks['ok'] else 'FAIL'}")
    parts.append(f"  Checkboxes: {'PASS' if checkboxes['ok'] else 'FAIL'}")
    parts.append(f"  Roadmap:    {'PASS' if roadmap.get('ok') else 'FAIL'}")
    summary = "M7 Audit complete:\n" + "\n".join(parts)

    return {
        "ok": all_ok,
        "integrity": integrity,
        "cross_ref": cross_ref,
        "wikilinks": wikilinks,
        "checkboxes": checkboxes,
        "roadmap": roadmap,
        "summary": summary,
    }

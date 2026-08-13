"""Orchestrator — lightweight coordination of the existing control-plane agents.

The Orchestrator does NOT replace or modify agents. It reads task nodes from
the Obsidian vault (``obsidian_vault/03-Tasks/``), resolves the agent assigned
to each task via the existing agent registry (``scripts/core/agents/``), builds
a context-limited prompt, dispatches through the same ``opencode run`` command
the terminal and workers use, tracks task state, and writes results back to the
task node.

Safety:
  * ``dispatch`` is a dry-run unless ``--yes`` is given (explicit authorization).
  * Only the task node's frontmatter ``status`` / ``updated`` fields and the
    ``## Execution Log`` section are modified; the rest of the Markdown is
    preserved byte-for-byte (atomic write via temp file + ``os.replace``).
  * Context is limited to the task node plus nodes named in its frontmatter
    (assigned agent, related component, dependencies) — never the whole vault.
  * Every change is logged to ``_logs/orchestrator.log``.

Usage (from the repo root):

    python -m scripts.core.orchestrator list [--status <s>] [--vault <path>]
    python -m scripts.core.orchestrator show <Task_Node> [--vault <path>]
    python -m scripts.core.orchestrator set-status <Task_Node> <status>
    python -m scripts.core.orchestrator dispatch <Task_Node> [--yes] [--vault <path>]
    python -m scripts.core.orchestrator report <Task_Node> <outcome> [--vault <path>]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.core import opencode_cfg  # noqa: E402
from scripts.core import roles  # noqa: E402
from scripts.core.agents import AGENT_SPEC_BY_AGENT  # noqa: E402
from scripts.core.context_resolver import (  # noqa: E402
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    cmd_context,
    resolve_context,
)
from scripts.core.run_hub import _build_run_command, _opencode_command  # noqa: E402
from scripts.core.vault_bridge import (  # noqa: E402
    FRONTMATTER_RE,
    KEY_LINE_RE,
    LINK_RE,
    VALID_STATUSES,
    VaultError,
    _atomic_write,
    _find_node,
    _log,
    _now,
    _replace_frontmatter,
    is_dispatchable,
    list_tasks,
    parse_frontmatter,
    read_task,
    resolve_task,
    update_task,
    validate_vault,
)

# ---------------------------------------------------------------- constants

DEFAULT_VAULT = _REPO_ROOT / "obsidian_vault"

# Allowed transitions: from -> set of allowed next statuses.
TRANSITIONS: dict[str, set[str]] = {
    "planned": {"ready", "blocked"},
    "ready": {"in_progress", "blocked"},
    "in_progress": {"completed", "blocked", "failed"},
    "blocked": {"ready", "in_progress"},
    "completed": set(),
    "failed": set(),
}

MAX_CONTEXT_NODES = 5  # extra linked nodes read beyond the task node itself

# Concurrency locks: _logs/locks/<sha1-of-task-name>.lock (atomic O_EXCL).
LOCK_DIR = Path("_logs") / "locks"


# ---------------------------------------------------------------- vault access


def resolve_vault(path_arg: str | None) -> Path:
    """Vault path: CLI arg > ZOVA_VAULT env > repo default."""
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    env = os.environ.get("ZOVA_VAULT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_VAULT


def _task_file(vault: Path, name: str) -> Path:
    """Resolve a task node name to a safe path inside 03-Tasks/.

    Raises VaultError when the name is unsafe (traversal/absolute/separators);
    a safe-but-missing name is resolved and left for ``read_task`` to report.
    """
    path = resolve_task(vault, name)
    if path is None:
        raise VaultError(f"invalid task name: {name!r}")
    return path


def _append_execution_log(body: str, outcome: str, detail: str = "") -> str:
    """Append a timestamped entry under a task's '## Execution Log' section.

    Creates the section when absent; preserves all other content.
    """
    entry = f"- {_now()} — {outcome}" + (f" — {detail}" if detail else "")
    heading = "## Execution Log"
    lines = body.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == heading), None)
    if idx is None:
        trimmed = body.rstrip()
        return trimmed + ("\n\n" if trimmed else "") + f"{heading}\n\n{entry}\n"
    # Insert after the heading, before the next heading or the end.
    insert_at = idx + 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    indent = "\n" if insert_at >= len(lines) or lines[insert_at].strip() else "\n"
    lines.insert(insert_at, indent + entry)
    return "\n".join(lines) + ("\n" if not body.endswith("\n") else "")


# ---------------------------------------------------------------- controlled execution


def _lock_path(name: str) -> Path:
    """Stable per-task lock path: _logs/locks/<sha1>.lock."""
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    return _REPO_ROOT / LOCK_DIR / f"{digest}.lock"


def _acquire_lock(name: str) -> Path | None:
    """Atomically claim the per-task lock; None if already held."""
    lock = _lock_path(name)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"[{_now()}] dispatch {name}\n".encode("utf-8"))
        os.close(fd)
        return lock
    except FileExistsError:
        return None
    except OSError:
        return None  # lock failure is non-fatal; logging still records it


def _release_lock(lock: Path | None) -> None:
    if lock is not None:
        lock.unlink(missing_ok=True)


def _extract_acceptance_criteria(body: str) -> list[str]:
    """Checklist lines under '## Acceptance Criteria' (tolerant parse)."""
    heading = "## Acceptance Criteria"
    lines = body.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == heading), None)
    if idx is None:
        return []
    criteria: list[str] = []
    for ln in lines[idx + 1:]:
        stripped = ln.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith(("- [ ]", "- [x]", "- [X]", "* [ ]")):
            criteria.append(stripped)
    return criteria


REPORT_FIELDS = ("actions performed", "files changed", "tests executed",
                 "test results", "remaining issues")


def _parse_agent_report(stdout: str) -> dict[str, str]:
    """Parse the '## Agent Report' section out of an agent's stdout.

    Tolerant: a missing section yields empty strings (reported as '(no
    report)'); unknown lines inside the section are ignored. Bullet lists
    are joined with '; '.
    """
    report: dict[str, str] = {f: "" for f in REPORT_FIELDS}
    heading = "## Agent Report"
    m = re.search(rf"^{re.escape(heading)}\s*$.*?(?=^## |\Z)", stdout,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return report
    section = m.group(0)
    current: str | None = None
    for line in section.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped == heading:
            continue
        lowered = stripped.lstrip("-* ").lower()
        matched = next((f for f in REPORT_FIELDS if lowered.startswith(f)), None)
        if matched:
            current = matched
            value = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            report[current] = value
        elif current is not None and stripped.startswith(("-", "*")):
            item = stripped.lstrip("-* ").strip()
            if item:
                report[current] = (report[current] + "; " + item).strip("; ")
    return report


_FAIL_MARKER = re.compile(r"\b(\d+)\s*(fail|error|broken)\b|\b0\s+passed\b")


def _decide_status(exit_ok: bool, report: dict[str, str]) -> str:
    """Map execution outcome + agent report -> task status.

    completed  — run ok AND tests reported as passing.
    blocked    — run ok but tests show failures (work is done, not green).
    failed     — non-zero exit or no report at all.

    Count-aware: 'pass 12 tests, 0 failures' is PASSING; 'fail 3 tests' or
    '2 errors' or '0 passed' is blocked.
    """
    if not exit_ok:
        return "failed"
    if not report.get("actions performed"):
        return "failed"  # nothing was actually done
    tests = (report.get("test results") or "").lower()
    if _FAIL_MARKER.search(tests):
        return "blocked"
    return "completed"


def _git_changed_files() -> list[str]:
    """Files the workspace git knows changed (porcelain, short)."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        entry = line[3:].strip()
        if not entry:
            continue
        # Renames print as 'old -> new'; record both paths so a rename is
        # never invisible to the scope-drift check.
        if " -> " in entry:
            old, _, new = entry.partition(" -> ")
            out.extend(p.strip() for p in (old, new) if p.strip())
        else:
            out.append(entry)
    return out


# ---------------------------------------------------------------- resolution


def resolve_agent_node(fields: dict[str, str]) -> tuple[str, str] | None:
    """Resolve assigned_agent ('Agent_Matthew') -> (agent key, model).

    Returns None when unassigned, malformed, or the agent key is unknown.
    """
    assigned = (fields.get("assigned_agent") or "").strip()
    if not assigned or assigned.startswith("Agent_") is False:
        return None
    key = assigned[len("Agent_"):].lower()
    spec = AGENT_SPEC_BY_AGENT.get(key)
    if spec is None:
        return None
    return spec.agent, opencode_cfg.resolve_model(spec.agent) or ""


def task_role_context(agent_key: str, fields: dict[str, str]) -> str:
    """Role context for a dispatch (temporary task-level override or assigned).

    A task node may carry an optional frontmatter ``role`` field naming one
    role id. When present it **overrides** the agent's persistent role
    assignments for this run only (precedence: user_role > role_default) and
    never mutates ``roles.json``. When absent, the agent's assigned roles are
    used. An unknown override id is an error (rejected, not silently ignored).
    """
    override = (fields.get("role") or "").strip()
    if not override:
        return roles.agent_context(agent_key, repo_root=_REPO_ROOT)
    if roles.get_role(override, repo_root=_REPO_ROOT) is None:
        raise VaultError(f"task role override {override!r} is not a known role")
    return roles.render_role_context(agent_key, role_ids=[override], repo_root=_REPO_ROOT)


def collect_context(vault: Path, fields: dict[str, str], body: str) -> list[Path]:
    """Read only the linked nodes named by the task (bounded).

    Follows ``assigned_agent``, ``related_component``, ``dependencies`` and
    body ``[[WikiLinks]]``, resolving each to a ``<name>.md`` file anywhere in
    the vault, capped at MAX_CONTEXT_NODES. Never walks the whole vault.
    """
    wanted: list[str] = []
    for key in ("assigned_agent", "related_component"):
        val = (fields.get(key) or "").strip()
        if val and val not in wanted:
            wanted.append(val)
    for name in re.split(r"[,\s]+", (fields.get("dependencies") or "").strip("[] ")):
        if name and name not in wanted:
            wanted.append(name)
    for m in LINK_RE.finditer(body):
        target = m.group(1).strip()
        if target and target not in wanted:
            wanted.append(target)

    found: list[Path] = []
    for name in wanted[:MAX_CONTEXT_NODES]:
        if name == "Tasks_Home" or name.endswith("_Home") or name == "Task_Backlog":
            continue
        hit = _find_node(vault, name)
        if hit is not None:
            found.append(hit)
    return found

# ---------------------------------------------------------------- commands


def cmd_list(vault: Path, status_filter: str | None) -> int:
    tasks = list_tasks(vault)
    if not tasks:
        print("No task nodes found in 03-Tasks/.")
        return 0
    print(f"{'Task':<28} {'Status':<12} {'Priority':<9} {'Agent'}")
    for path in tasks:
        fields, _body, _raw = read_task(path)
        if status_filter and fields.get("status") != status_filter:
            continue
        print(f"{path.stem:<28} {fields.get('status', '?'):<12} "
              f"{fields.get('priority', '?'):<9} {fields.get('assigned_agent', '—')}")
    return 0


def cmd_show(vault: Path, name: str) -> int:
    path = _task_file(vault, name)
    fields, body, _raw = read_task(path)
    print(f"# {name}")
    for key in ("title", "status", "priority", "assigned_agent",
                "related_component", "dependencies", "created", "updated"):
        if key in fields:
            print(f"{key}: {fields[key]}")
    print("---")
    print(body.strip())
    print("---")
    package = resolve_context(vault, path)
    if package.nodes:
        print("Linked context (resolver):")
        for ref in package.nodes:
            print(f"  - d{ref.depth} [[{ref.name}]] ({ref.type})")
    if package.unresolved:
        print(f"unresolved: {', '.join(package.unresolved)}")
    if package.cycles:
        print(f"cycles: {', '.join(f'{a}->{b}' for a, b in package.cycles)}")
    return 0


def _transition(name: str, fields: dict[str, str], new_status: str) -> str:
    current = fields.get("status", "")
    if new_status not in VALID_STATUSES:
        raise VaultError(f"invalid status {new_status!r}; allowed: {', '.join(sorted(VALID_STATUSES))}")
    if new_status == current:
        return "no-op"
    allowed = TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise VaultError(f"illegal transition {current} -> {new_status} (allowed: {', '.join(sorted(allowed)) or 'none'})")
    return "ok"


def cmd_set_status(vault: Path, name: str, new_status: str, force: bool = False) -> int:
    path = _task_file(vault, name)
    fields, _body, _raw = read_task(path)
    if fields.get("status") == new_status:
        print(f"{name}: already {new_status} (no-op)")
        return 0
    _transition(name, fields, new_status)
    update_task(path, "set-status", {"status": new_status, "updated": _now()[:10]})
    _log(f"set-status {name}: {fields.get('status')} -> {new_status}")
    print(f"{name}: {fields.get('status')} -> {new_status}")
    return 0


MOCK_AGENT_REPORT = """\
Done. Everything is implemented.

## Agent Report
- actions performed: implemented feature; added tests
- files changed: scripts/core/example.py; test/tests/test_example.py
- tests executed: python -m unittest test.tests.test_example
- test results: pass 12 tests, 0 failures
- remaining issues: none
"""


def cmd_dispatch(vault: Path, name: str, yes: bool = False, mock: bool = False) -> int:
    path = _task_file(vault, name)
    fields, body, raw = read_task(path)
    status = fields.get("status", "")

    # Requirement 1 — execute only tasks with status == 'ready'.
    if status != "ready":
        hint = "mark ready first: set-status <Task> ready" if status == "planned" else ""
        raise VaultError(f"{name}: cannot dispatch while status={status}"
                         + (f" ({hint})" if hint else ""))
    ok_dispatch, why = is_dispatchable(fields)
    if not ok_dispatch:
        raise VaultError(f"{name}: cannot dispatch — {why}")

    resolved = resolve_agent_node(fields)
    if resolved is None:
        raise VaultError(
            f"{name}: assigned_agent missing/unknown — cannot dispatch. "
            f"Expected e.g. 'Agent_Matthew'."
        )
    agent_key, model = resolved
    if not model:
        raise VaultError(f"{name}: agent {agent_key!r} has no configured model")

    # Requirement 2–3 — resolve approved context before execution.
    package = resolve_context(vault, path)
    ctx = [Path(ref.path) for ref in package.nodes]
    prompt = _build_prompt(name, fields, body, ctx)
    role_ctx = task_role_context(agent_key, fields)
    if role_ctx:
        prompt = role_ctx + "\n" + prompt
    exe = _opencode_command() or "opencode"
    cmd = _build_run_command(exe, agent_key, prompt, model)

    print(f"task      : {name}")
    print(f"agent     : {agent_key} ({model})")
    print(f"context   : {len(ctx)} linked node(s)")
    print(f"command   : {' '.join(cmd)}")
    if not yes:
        print("\nDRY-RUN: pass --yes to actually execute (explicit authorization required).")
        return 0

    # Requirement 11 — per-task concurrency lock (atomic O_EXCL).
    lock = _acquire_lock(name)
    if lock is None:
        raise VaultError(f"{name}: already executing (lock held) — concurrent dispatch refused")
    outcome = "failed"
    detail = ""
    try:
        # Authorized execution.
        _transition(name, fields, "in_progress")
        _log(f"dispatch {name}: starting {agent_key} (authorized --yes)")
        if mock:
            print(MOCK_AGENT_REPORT)
            stdout = MOCK_AGENT_REPORT
        else:
            stdout = _run_command_capture(cmd)
        ok = (stdout is not None)
        report = _parse_agent_report(stdout or "")
        outcome = _decide_status(ok, report)

        # Requirement 9 — scope-drift detection (reported, never hidden).
        changed = _git_changed_files()
        if report.get("files changed"):
            drift = [f for f in report["files changed"].split("; ") if f and f not in changed]
            if drift:
                _log(f"dispatch {name}: scope drift — reported but not in git status: {drift}")
                detail = f"scope drift: {', '.join(drift)}"

        if not ok:
            detail = (detail + " ; " if detail else "") + "agent process failed to start/complete"
        elif not report.get("actions performed"):
            detail = (detail + " ; " if detail else "") + "no Agent Report section in output"
    finally:
        # Requirement 5–6 — write the outcome back to the task node.
        new_body = _append_execution_log(body, outcome, detail)
        try:
            update_task(path, "dispatch", {"status": outcome, "updated": _now()[:10]},
                        new_body=new_body)
        except Exception as exc:  # noqa: BLE001 — log-and-continue
            _log(f"dispatch {name}: failed to write result back: {exc}")
        _release_lock(lock)

    _log(f"dispatch {name}: result={outcome} (report={bool(report.get('actions performed'))})")
    print(f"result    : {outcome}")
    return 0 if outcome == "completed" else 1


def _build_prompt(name: str, fields: dict[str, str], body: str, ctx: list[Path]) -> str:
    parts = [f"Task: {name}"]
    if fields.get("title"):
        parts.append(f"Title: {fields['title']}")
    desc = body.strip()
    if desc:
        parts.append("---\n" + desc)
    criteria = _extract_acceptance_criteria(body)
    if criteria:
        parts.append("---\nAcceptance Criteria (must all pass):")
        parts.extend(criteria)
    if ctx:
        parts.append("---\nRelevant context (linked nodes):")
        for p in ctx:
            try:
                snippet = p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                snippet = "(unreadable)"
            parts.append(f"\n### {p.stem}\n{snippet[:800]}")
    # Requirement 9 — scope guard: work only within the related component.
    component = (fields.get("related_component") or "").strip()
    if component:
        parts.append(
            f"---\nScope: work ONLY within component {component} and its files. "
            "Never modify unrelated modules. NEVER delete files or run destructive "
            "commands (rm, del, drop, force-push, etc.) without explicit user authorization."
        )
    # Requirement 4 — mandatory structured report.
    parts.append(
        "---\nWhen finished, end your response with exactly:\n"
        "## Agent Report\n"
        "- actions performed: <list>\n"
        "- files changed: <list>\n"
        "- tests executed: <list>\n"
        "- test results: <pass|fail|skipped + counts>\n"
        "- remaining issues: <list or none>\n"
    )
    return "\n".join(parts)


def _body_after_frontmatter(text: str) -> str:
    m = FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def _with_body(text: str, new_body: str) -> str:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return text
    return text[: m.end()] + new_body


def _run_command_capture(cmd: list[str]) -> str | None:
    """Run the opencode command; return full stdout, or None on failure.

    Streams output to the console as it arrives AND captures it for the
    Agent Report parser. Safe: argv form, no shell.
    """
    chunks: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        _log(f"dispatch: failed to start opencode: {exc}")
        return None
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        chunks.append(line)
    rc = proc.wait()
    if rc != 0:
        _log(f"dispatch: opencode exit code {rc}")
    return "".join(chunks)


def cmd_report(vault: Path, name: str, outcome: str) -> int:
    path = _task_file(vault, name)
    fields, body, _raw = read_task(path)
    if outcome not in ("completed", "failed", "blocked"):
        raise VaultError(f"outcome must be completed|failed|blocked, got {outcome!r}")
    current = fields.get("status", "")
    try:
        _transition(name, fields, outcome)
    except VaultError:
        # Allow a report to record a failed run even if the transition set
        # would reject it (e.g. failed from ready) — a failed attempt is fact.
        if outcome != "failed":
            raise
    new_body = _append_execution_log(body, outcome)
    update_task(path, "report", {"status": outcome, "updated": _now()[:10]}, new_body=new_body)
    _log(f"report {name}: recorded {outcome}")
    print(f"{name}: recorded {outcome} (was {current})")
    return 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    # Console-safe output on legacy Windows codepages (cp1252 can't print ↑/↓).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        prog="python -m scripts.core.orchestrator",
        description="Coordinate the existing agents via Obsidian vault task nodes.",
    )
    parser.add_argument("--vault", dest="vault_main", default=None,
                        help="vault path (default: repo obsidian_vault, or $ZOVA_VAULT)")
    sub = parser.add_subparsers(dest="command", required=True)

    # Every subcommand also accepts --vault (after the subcommand name).
    vault_parent = argparse.ArgumentParser(add_help=False)
    vault_parent.add_argument("--vault", dest="vault_sub", default=None, help="vault path")
    p_list = sub.add_parser("list", help="list task nodes", parents=[vault_parent])

    p_list.add_argument("--status", default=None, help="filter by status")

    p_show = sub.add_parser("show", help="show a task node + linked context", parents=[vault_parent])
    p_show.add_argument("name")

    p_set = sub.add_parser("set-status", help="transition a task node's status", parents=[vault_parent])
    p_set.add_argument("name")
    p_set.add_argument("status")

    p_dispatch = sub.add_parser("dispatch", help="build & (with --yes) run a task", parents=[vault_parent])
    p_dispatch.add_argument("name")
    p_dispatch.add_argument("--yes", action="store_true", help="authorize execution")
    p_dispatch.add_argument("--mock", action="store_true",
                            help="[test] use a mock agent that prints a passing Agent Report")

    p_report = sub.add_parser("report", help="record an execution result", parents=[vault_parent])
    p_report.add_argument("name")
    p_report.add_argument("outcome")

    p_ctx = sub.add_parser("context", help="resolve a task's linked context package",
                           parents=[vault_parent])
    p_ctx.add_argument("name")
    p_ctx.add_argument("--depth", type=int, default=DEFAULT_MAX_DEPTH,
                       help=f"max traversal depth (default {DEFAULT_MAX_DEPTH})")
    p_ctx.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES,
                       help=f"max context nodes (default {DEFAULT_MAX_NODES})")

    args = parser.parse_args(argv)
    vault_arg = getattr(args, "vault_sub", None) or getattr(args, "vault_main", None)
    try:
        vault = resolve_vault(vault_arg)
        if args.command == "list":
            return cmd_list(vault, args.status)
        if args.command == "show":
            return cmd_show(vault, args.name)
        if args.command == "set-status":
            return cmd_set_status(vault, args.name, args.status)
        if args.command == "dispatch":
            return cmd_dispatch(vault, args.name, yes=args.yes, mock=args.mock)
        if args.command == "report":
            return cmd_report(vault, args.name, args.outcome)
        if args.command == "context":
            return cmd_context(vault, args.name, args.depth, args.max_nodes)
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _log(f"error: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 — safe reporting for any failure
        print(f"error: unexpected: {exc}", file=sys.stderr)
        _log(f"error: unexpected: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

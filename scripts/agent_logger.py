"""Dynamic, config-driven agent logging for the Obsidian vault.

Pure-stdlib module that creates and maintains per-agent markdown log files
inside ``obsidian_vault/agents_logs/``. Only agents that participate in the
current dispatch are tracked — when the active set changes,stale historical log files are
left in place (never deleted) while the canonical humanified logs receive new entries.

Each agent log file records:
  * Active Role & Scope — the agent's responsibility in the project.
  * Task Execution & Code Changes — a running record of tasks handled.
  * WikiLinks Traceability — back-links to the originating prompt logs.

No third-party imports; atomic writes via tempfile + os.replace; safe to
call from any thread.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

# Workspace root mirrors scripts/terminal_app.py.
_PROJECT_ROOT = Path(os.getcwd())

# Default vault agents_logs directory relative to the workspace root.
DEFAULT_AGENTS_DIR = _PROJECT_ROOT / "obsidian_vault" / "agents_logs"

# Agent role descriptions now live in scripts/core/agents/ (one spec per
# agent); re-export for legacy callers that import ROLE_DESCRIPTIONS here.
from scripts.core.agents import ROLE_DESCRIPTIONS  # noqa: E402

_lock = threading.Lock()
_ACTIVE_AGENT_CACHE: set[str] = set()

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# --------------------------------------------------------------------------- helpers


def _safe_agent_filename(tag: str) -> str:
    """Return the canonical humanified log filename for an agent tag."""
    from scripts.core.agents import AGENTS  # avoid circular import at module level

    for agent_tag, name, _agent in AGENTS:
        if agent_tag == tag:
            safe_name = re.sub(r"[^a-zA-Z0-9_ -]", "", name)
            safe_name = re.sub(r"\s+", "_", safe_name)
            return f"{tag.upper()}_{safe_name}.md"
    return f"{tag.upper()}.md"


def _render_agent_template(
    template_path: Path,
    variables: dict[str, str],
) -> str:
    """Fill ``{{placeholders}}`` in the agent template, with fallback."""
    if not template_path.exists():
        return _agent_fallback(variables)
    try:
        raw = template_path.read_text(encoding="utf-8")
    except OSError:
        return _agent_fallback(variables)

    def replacer(match: re.Match) -> str:
        return variables.get(match.group(1), match.group(0))

    return _PLACEHOLDER_RE.sub(replacer, raw)


def _agent_fallback(variables: dict[str, str]) -> str:
    """Minimal agent log when the template is missing."""
    tag = variables.get("agent_tag", "?")
    role = variables.get("agent_role", "?")
    internal = variables.get("agent_internal", "?")
    return (
        f"---\n"
        f'agent_tag: "{tag}"\n'
        f'agent_role: "{role}"\n'
        f'agent_internal: "{internal}"\n'
        f'status: "active"\n'
        f'last_updated: "{variables.get("last_updated", "")}"\n'
        f"---\n\n"
        f"# {tag} — {role} (`{internal}`)\n\n"
        f"## Active Role & Scope\n\n"
        f"{variables.get('role_description', 'No description.')}\n\n"
        f"## Task Execution & Code Changes\n\n"
    )


def _run_entry(
    timestamp: str,
    prompt_log_id: str,
    prompt_text: str,
    status: str,
    duration_s: float | None = None,
) -> str:
    """Format a single run entry for the agent's task log."""
    prompt_link = f"[[../prompts/{prompt_log_id}]]"
    duration_str = f" ({duration_s:.1f}s)" if duration_s is not None else ""
    short_prompt = prompt_text[:80].replace("\n", " ")
    if len(prompt_text) > 80:
        short_prompt += "…"
    icon = "✅" if status == "ok" else ("❌" if status == "failed" else "⏳")
    return (
        f"### {timestamp} — {icon} {prompt_link}\n\n"
        f"> *Prompt:* {short_prompt}{duration_str}\n\n"
    )


# --------------------------------------------------------------------------- public API


def ensure_agent_logs(
    agent_tags: list[str],
    agents_dir: str | os.PathLike | None = None,
    template_path: str | os.PathLike | None = None,
) -> list[Path]:
    """Create per-agent log files for every tag in ``agent_tags``.

    Existing canonical files are left untouched (they serve as persistent history).
    New canonical files are created from the template. Historical files for agents
    not in ``agent_tags`` are **not deleted** — they are preserved for audit traceability.

    Args:
        agent_tags: Tags of the currently dispatched agents (e.g.
            ``[\"m1\",\"m4\"]``).
        agents_dir: Override the default ``obsidian_vault/agents_logs/``.
        template_path: Override ``_TEMPLATE.md`` inside ``agents_dir``.

    Returns:
        List of ``Path`` objects for all active agent log files.
    """
    from scripts.core.agents import AGENTS  # avoid circular import

    directory = Path(agents_dir) if agents_dir is not None else DEFAULT_AGENTS_DIR
    directory.mkdir(parents=True, exist_ok=True)

    tmpl = (
        Path(template_path)
        if template_path is not None
        else directory / "_TEMPLATE.md"
    )

    tag_map: dict[str, tuple[str, str]] = {
        t: (n, a) for t, n, a in AGENTS
    }

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    paths: list[Path] = []

    with _lock:
        _ACTIVE_AGENT_CACHE.clear()
        _ACTIVE_AGENT_CACHE.update(agent_tags)

    for tag in agent_tags:
        name, agent = tag_map.get(tag, (tag.upper(), tag))
        filename = _safe_agent_filename(tag)
        filepath = directory / filename

        if not filepath.exists():
            variables: dict[str, str] = {
                "agent_tag": tag.upper(),
                "agent_role": name,
                "agent_internal": agent,
                "last_updated": now,
                "role_description": ROLE_DESCRIPTIONS.get(
                    agent, f"No role description configured for `{agent}`."
                ),
            }
            content = _render_agent_template(tmpl, variables)
            fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".agent.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(content)
                os.replace(tmp, filepath)
            except Exception:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise

        paths.append(filepath)

    return paths


def append_agent_run(
    tag: str,
    prompt_text: str,
    prompt_log_id: str,
    status: str = "dispatched",
    duration_s: float | None = None,
    agents_dir: str | os.PathLike | None = None,
) -> Path | None:
    """Append a run entry to the agent's task log.

    Only writes when the agent is in the currently active set (as established
    by the last ``ensure_agent_logs`` call). Agents not in the active set are
    silently skipped.

    Args:
        tag: Agent tag (e.g. ``\"m4\"``).
        prompt_text: The (pruned) prompt text for context.
        prompt_log_id: The prompt log session ID (e.g. ``\"prompt-003\"``).
        status: ``\"ok\"``, ``\"failed\"``, or ``\"dispatched\"``.
        duration_s: Optional duration in seconds for the run.
        agents_dir: Override the default directory.

    Returns:
        The agent log ``Path``, or ``None`` when skipped.
    """
    directory = Path(agents_dir) if agents_dir is not None else DEFAULT_AGENTS_DIR

    filename = _safe_agent_filename(tag)
    filepath = directory / filename

    if not filepath.exists():
        # Ensure the file exists (e.g. agent was not in the original dispatch
        # but we want to record it anyway — creates a minimal fallback log).
        ensure_agent_logs([tag], agents_dir=agents_dir)
        if not filepath.exists():
            return None

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = _run_entry(timestamp, prompt_log_id, prompt_text, status, duration_s)

    # Append the entry without rewriting the entire file.
    try:
        with open(filepath, "a", encoding="utf-8") as fh:
            fh.write(entry)
    except OSError:
        return None

    # Update the frontmatter last_updated field.
    _update_last_updated(filepath, timestamp)

    return filepath


def _update_last_updated(filepath: Path, timestamp: str) -> None:
    """Patch the ``last_updated`` field in the frontmatter."""
    try:
        raw = filepath.read_text(encoding="utf-8")
    except OSError:
        return
    updated = re.sub(
        r'^last_updated: ".*"$',
        f'last_updated: "{timestamp}"',
        raw,
        count=1,
        flags=re.MULTILINE,
    )
    if updated != raw:
        fd, tmp = tempfile.mkstemp(
            dir=str(filepath.parent), suffix=".agent.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(updated)
            os.replace(tmp, filepath)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def active_agents(agents_dir: str | os.PathLike | None = None) -> set[str]:
    """Return the set of agent tags that currently have log files.

    This reflects the *persisted* active set on disk, not the in-memory
    cache. Useful for vault health checks.
    """
    directory = Path(agents_dir) if agents_dir is not None else DEFAULT_AGENTS_DIR
    if not directory.is_dir():
        return set()
    active: set[str] = set()
    pattern = re.compile(r"^(M\d)_.*\.md$", re.IGNORECASE)
    for entry in directory.iterdir():
        match = pattern.match(entry.name)
        if match:
            active.add(match.group(1).lower())
    return active


def cached_active_agents() -> set[str]:
    """Return the in-memory active agent set (thread-safe snapshot)."""
    with _lock:
        return set(_ACTIVE_AGENT_CACHE)

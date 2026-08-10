"""Automated prompt-logging mechanism for the Obsidian vault.

Pure-stdlib module that generates timestamped, sequentially-named prompt
log markdown files inside ``obsidian_vault/prompts/`` whenever a major
prompt or task instruction is processed. Each file includes YAML-alike
frontmatter, the full prompt text, and WikiLinks back to the Roadmap and
related agent logs.

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

# Default vault prompts directory relative to the workspace root.
DEFAULT_PROMPTS_DIR = _PROJECT_ROOT / "obsidian_vault" / "prompts"

# Sequential counter lock + next index.
_lock = threading.Lock()
_next_index: int | None = None


def _discover_next_index(prompts_dir: Path) -> int:
    """Scan ``prompts_dir`` for existing prompt-NNN.md files and return the
    next available index (max+1, or 1 when the directory is empty)."""
    max_idx = 0
    pattern = re.compile(r"^prompt-(\d+)\.md$")
    try:
        for entry in prompts_dir.iterdir():
            match = pattern.match(entry.name)
            if match:
                max_idx = max(max_idx, int(match.group(1)))
    except OSError:
        pass
    return max_idx + 1


def _next_sequence(prompts_dir: Path) -> int:
    """Thread-safe incrementing prompt-log sequence number."""
    global _next_index
    with _lock:
        if _next_index is None:
            _next_index = _discover_next_index(prompts_dir)
        idx = _next_index
        _next_index += 1
        return idx


def _safe_filename(text: str, max_len: int = 50) -> str:
    """Turn a prompt snippet into a safe short slug for the filename."""
    slug = re.sub(r"[^a-zA-Z0-9_ -]", "", text)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-") or "prompt"


def _wiki_link(page: str, anchor: str | None = None) -> str:
    """Format an Obsidian WikiLink ``[[page]]`` or ``[[page#anchor]]``."""
    if anchor:
        return f"[[{page}#{anchor}]]"
    return f"[[{page}]]"


def _affected_file_links(files: list[str] | None = None) -> str:
    """Render affected file entries as WikiLinks when they live in the project."""
    if not files:
        return "*No affected files recorded.*"
    lines: list[str] = []
    for f in files:
        lines.append(f"- `{f}`")
    return "\n".join(lines)


def _agent_log_links(agent_tags: list[str] | None = None) -> str:
    """Render agent-run links as Obsidian WikiLinks pointing into agents_logs/."""
    if not agent_tags:
        return "*No agent logs linked.*"
    lines: list[str] = []
    for tag in agent_tags:
        tag_upper = tag.upper()
        lines.append(f"- {_wiki_link(f'../agents_logs/{tag_upper}')}")
    return "\n".join(lines)


_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _render_template(
    template_path: Path,
    variables: dict[str, str],
) -> str:
    """Fill ``{{placeholders}}`` in the template with variable values."""
    if not template_path.exists():
        return _fallback_content(variables)
    try:
        raw = template_path.read_text(encoding="utf-8")
    except OSError:
        return _fallback_content(variables)

    def replacer(match: re.Match) -> str:
        return variables.get(match.group(1), match.group(0))

    return _PLACEHOLDER_RE.sub(replacer, raw)


def _fallback_content(variables: dict[str, str]) -> str:
    """Return a minimal prompt-log when the template file is missing."""
    return (
        f"---\n"
        f'timestamp: "{variables.get("timestamp", "")}"\n'
        f'target_agent: "{variables.get("target_agent", "")}"\n'
        f'status: "{variables.get("status", "")}"\n'
        f"---\n\n"
        f"# Prompt Log — {variables.get('session_id', '')}\n\n"
        f"## User Prompt\n\n"
        f"```\n{variables.get('prompt_content', '')}\n```\n"
    )


def log_prompt(
    prompt: str,
    target_agents: list[str] | None = None,
    affected_files: list[str] | None = None,
    active_tab: str = "master",
    prompts_dir: str | os.PathLike | None = None,
    template_path: str | os.PathLike | None = None,
) -> Path:
    """Generate a sequentially-numbered prompt log markdown file.

    Args:
        prompt: The raw user prompt text.
        target_agents: Tags dispatched to (e.g. ``["m1","m4"]``); ``None``
            means "all agents."
        affected_files: Repository-relative paths of files touched by the
            run (best-effort; empty when unknown).
        active_tab: The tab from which the prompt was dispatched.
        prompts_dir: Override the default ``obsidian_vault/prompts/``.
        template_path: Override ``_TEMPLATE.md`` inside ``prompts_dir``.

    Returns:
        The written ``Path``.
    """
    directory = Path(prompts_dir) if prompts_dir is not None else DEFAULT_PROMPTS_DIR
    directory.mkdir(parents=True, exist_ok=True)

    seq = _next_sequence(directory)
    slug = _safe_filename(prompt)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session_id = f"prompt-{seq:03d}"

    agents_label = ", ".join(target_agents) if target_agents else "MASTER (all agents)"
    variables: dict[str, str] = {
        "timestamp": timestamp,
        "target_agent": agents_label,
        "status": "dispatched",
        "session_id": session_id,
        "active_tab": active_tab,
        "prompt_content": prompt.strip(),
        "affected_files": _affected_file_links(affected_files),
        "agent_log_links": _agent_log_links(target_agents),
    }

    tmpl = (
        Path(template_path)
        if template_path is not None
        else directory / "_TEMPLATE.md"
    )
    content = _render_template(tmpl, variables)
    filename = f"{session_id}.md"
    filepath = directory / filename

    # Atomic write.
    fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".prompt.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, filepath)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    return filepath

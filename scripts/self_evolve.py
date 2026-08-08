"""Self-evolution engine for the MultiAgentCoding control plane.

Pure, stdlib-only module that supports the self-evolving code pipeline:

  * ``detect_optimization_loops`` — scans ``_logs/*.log`` for repeated failure
    signatures (>= ``LOOP_THRESHOLD`` occurrences) and returns ``Proposal``s.
  * ``SelfEvolveEngine`` — gatekeeper for self-modification:
      - ``allow_path`` restricts writes to ``PROJECT_ROOT``,
      - ``checkpoint`` records a decision + git HEAD,
      - ``verify`` py_compiles ``scripts/*.py``, JSON-parses ``opencode.json``
        and runs the unittest suite,
      - ``write_restart_marker`` / ``read_restart_marker`` round-trip the JSON
        restart control file at ``_logs/restart.ctl``.

No third-party imports; no network access; never modifies files itself.
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Workspace root = the directory the launcher was launched from (mirrors
# scripts/unified_app.py so the engine targets the repo it runs in).
PROJECT_ROOT = Path(os.getcwd())

# Regex patterns for repeated failures scanned in agent logs.
FAILURE_SIGNATURES: list[re.Pattern[str]] = [
    re.compile(r"exit code", re.IGNORECASE),
    re.compile(r"Error:", re.IGNORECASE),
    re.compile(r"Traceback"),
    re.compile(r"ERROR:"),
]

# A signature must appear at least this many times to trigger a proposal.
LOOP_THRESHOLD = 3

# Restart control file name inside the _logs/ directory.
RESTART_MARKER_NAME = "restart.ctl"


@dataclass
class Proposal:
    """One detected optimization-loop candidate for a single agent/signature."""

    id: str
    agent: str
    signature: str
    count: int
    suggestion: str


def detect_optimization_loops(log_dir: str | os.PathLike | None = None) -> list[Proposal]:
    """Scan ``_logs/*.log`` for repeated failure signatures.

    Counts occurrences per agent per signature; any signature with at least
    ``LOOP_THRESHOLD`` matches produces a ``Proposal``. ``log_dir`` overrides
    the default ``PROJECT_ROOT/_logs`` (used by tests). Missing/unreadable
    directories return an empty list.
    """
    directory = Path(log_dir) if log_dir is not None else PROJECT_ROOT / "_logs"
    proposals: list[Proposal] = []
    if not directory.is_dir():
        return proposals
    for log_file in sorted(directory.glob("*.log")):
        agent = log_file.stem
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in FAILURE_SIGNATURES:
            count = len(pattern.findall(text))
            if count >= LOOP_THRESHOLD:
                signature = pattern.pattern
                proposals.append(
                    Proposal(
                        id=f"{agent}:{signature}",
                        agent=agent,
                        signature=signature,
                        count=count,
                        suggestion=(
                            f"Review {agent} for repeated {signature!r} failures "
                            f"({count} occurrences) before the next self-evolve run."
                        ),
                    )
                )
    return proposals


class SelfEvolveEngine:
    """Gatekeeper for self-modification: allow, checkpoint, verify, restart."""

    def __init__(
        self,
        project_root: str | os.PathLike | None = None,
        record_decision=None,
    ) -> None:
        self.project_root = (
            Path(project_root) if project_root is not None else PROJECT_ROOT
        )
        # Optional callable(text) mirroring StateTracker.record_decision; kept
        # injectable so this module stays importable without web_app.
        self.record_decision = record_decision

    def allow_path(self, p: str | os.PathLike) -> bool:
        """True when ``p`` resolves inside ``PROJECT_ROOT`` (else deny)."""
        root = self.project_root.resolve()
        target = Path(p).resolve()
        return target == root or root in target.parents

    def checkpoint(self, prompt: str) -> dict:
        """Record a decision plus the git HEAD for a self-evolve run.

        Returns ``{"prompt", "git_head", "decision"}``. The decision is passed
        to ``record_decision`` when one was injected; git HEAD is read via
        ``git rev-parse HEAD`` (empty string when not a git repo).
        """
        head = self._git_head()
        decision = f"self-evolve checkpoint: {prompt} @ {head}"
        if self.record_decision is not None:
            self.record_decision(decision)
        return {"prompt": prompt, "git_head": head, "decision": decision}

    def _git_head(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return ""

    def verify(self, project_root: str | os.PathLike | None = None) -> dict:
        """Verify a project: py_compile + JSON-parse + unittest suite.

        Runs ``py_compile`` on every ``scripts/*.py``, JSON-parses
        ``opencode.json``, and runs ``python -m unittest discover test/tests``
        from ``project_root``. Returns ``{"ok", "stdout", "errors"}`` where
        ``ok`` is True only when every check passed.
        """
        root = Path(project_root) if project_root is not None else self.project_root
        errors: list[str] = []
        stdout_parts: list[str] = []

        scripts_dir = root / "scripts"
        if scripts_dir.is_dir():
            for py_file in sorted(scripts_dir.glob("*.py")):
                try:
                    py_compile.compile(str(py_file), doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(f"py_compile {py_file.name}: {exc}")

        config = root / "opencode.json"
        if config.exists():
            try:
                json.loads(config.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                errors.append(f"opencode.json: {exc}")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "test/tests"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            stdout_parts.append(result.stdout)
            if result.stderr:
                stdout_parts.append(result.stderr)
            if result.returncode != 0:
                errors.append(f"unittest suite failed (exit {result.returncode})")
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"unittest suite: {exc}")

        return {
            "ok": not errors,
            "stdout": "\n".join(stdout_parts),
            "errors": errors,
        }

    def write_restart_marker(
        self,
        control_path: str | os.PathLike | None = None,
        payload: dict | None = None,
    ) -> Path:
        """Atomically write the JSON restart marker (default ``_logs/restart.ctl``).

        Mirrors the atomic temp-file + ``os.replace`` pattern from web_app.py.
        Returns the marker path.
        """
        path = (
            Path(control_path)
            if control_path is not None
            else self.project_root / "_logs" / RESTART_MARKER_NAME
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(payload or {})
        data.setdefault("ts", datetime.now(timezone.utc).isoformat())
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".ctl.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    def read_restart_marker(
        self, control_path: str | os.PathLike | None = None
    ) -> dict | None:
        """Read the restart marker JSON, or None when missing/corrupt."""
        path = (
            Path(control_path)
            if control_path is not None
            else self.project_root / "_logs" / RESTART_MARKER_NAME
        )
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
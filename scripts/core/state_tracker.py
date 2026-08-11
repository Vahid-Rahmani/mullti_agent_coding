"""State tracker — reads/writes workspace ``state.md`` checkpoint.

Writes mirror ``_write_config`` (temp file + ``os.replace``) so a crash
never leaves a half-written state file.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .agents import PROJECT_ROOT


def _state_escape(text: str) -> str:
    """Escape backslashes/newlines for a single-line state.md field."""
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _state_unescape(text: str) -> str:
    """Invert _state_escape (only ``\\n`` and ``\\\\`` are escaped)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt == "n" else nxt)
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


class StateTracker:
    """Read/write the workspace ``state.md`` checkpoint (sections format)."""

    MAX_COMPLETED = 20

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else PROJECT_ROOT / "state.md"
        self.lock = threading.Lock()

    def load(self) -> dict | None:
        """Parse state.md into a dict, or None when missing/corrupt."""
        if not self.path.exists():
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        return self._parse(text)

    def update(self, **fields: object) -> dict:
        """Merge ``fields`` into the on-disk state and write atomically."""
        return self._mutate(lambda data: data.update(fields))

    def record_run(self, prompt: str, started: str) -> dict:
        return self.update(phase="running", last_run={"prompt": prompt, "started": started})

    def record_finish(self, tag: str, ok: bool) -> dict:
        return self._mutate(
            lambda data: data.setdefault("completed", []).append(
                f"{tag}: {'ok' if ok else 'failed'}"
            )
        )

    def record_decision(self, text: str) -> dict:
        return self._mutate(lambda data: data.setdefault("decisions", []).append(text))

    def record_pending_modification(self, detail: str) -> dict:
        return self.update(pending_modification=detail)

    def clear_pending_modification(self) -> dict:
        return self.update(pending_modification=None)

    def record_restart(self, action: str, result: str) -> dict:
        return self._mutate(
            lambda data: data.setdefault("restart_log", []).append(f"{action}: {result}")
        )

    # ------------------------------------------------------------ internals

    def _mutate(self, transform) -> dict:
        with self.lock:
            data = self.load() or {}
            transform(data)
            data = self._compress(data)
            self._write(data)
            return data

    def _compress(self, data: dict) -> dict:
        """Trim ``## Completed`` beyond MAX_COMPLETED into a summary line."""
        completed = list(data.get("completed") or [])
        if len(completed) > self.MAX_COMPLETED:
            excess = len(completed) - self.MAX_COMPLETED
            data["completed"] = [f"… {excess} earlier finishes compressed"] + completed[-self.MAX_COMPLETED:]
        return data

    def _parse(self, text: str) -> dict | None:
        """Split ``## Section`` blocks; None when no sections are present."""
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current = stripped[3:].strip()
                sections[current] = []
            elif current is not None:
                sections[current].append(line)
        if not sections:
            return None

        phase_lines = sections.get("Phase") or []
        phase = phase_lines[0].strip() if phase_lines and phase_lines[0].strip() else "idle"

        last_run = None
        run_lines = sections.get("Last Run") or []
        if run_lines:
            prompt = ""
            started = ""
            for line in run_lines:
                if line.startswith("prompt:"):
                    prompt = _state_unescape(line[len("prompt:"):].strip())
                elif line.startswith("started:"):
                    started = line[len("started:"):].strip()
            last_run = {"prompt": prompt, "started": started}

        def bullets(name: str) -> list[str]:
            out = []
            for line in sections.get(name) or []:
                item = line.strip().lstrip("-").strip()
                if item:
                    out.append(item)
            return out

        pending = "\n".join(sections.get("Pending Modification") or []).strip()
        settings: dict = {}
        settings_lines = sections.get("Settings") or []
        if settings_lines:
            try:
                parsed = json.loads("\n".join(settings_lines).strip())
                if isinstance(parsed, dict):
                    settings = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                settings = {}

        return {
            "phase": phase,
            "last_run": last_run,
            "completed": bullets("Completed"),
            "active_worktrees": bullets("Active Worktrees"),
            "decisions": bullets("Decisions"),
            "pending_modification": pending or None,
            "restart_log": bullets("Restart Log"),
            "settings": settings,
        }

    def _render(self, data: dict) -> str:
        lines = ["# State", ""]
        lines += ["## Phase", str(data.get("phase") or "idle"), ""]
        last_run = data.get("last_run")
        if last_run:
            lines += [
                "## Last Run",
                f"prompt: {_state_escape(str(last_run.get('prompt', '')))}",
                f"started: {str(last_run.get('started', ''))}",
                "",
            ]
        for key, heading in (
            ("completed", "Completed"),
            ("active_worktrees", "Active Worktrees"),
            ("decisions", "Decisions"),
        ):
            lines += [f"## {heading}"]
            lines += [f"- {entry}" for entry in (data.get(key) or [])]
            lines.append("")
        lines += ["## Pending Modification"]
        pending = data.get("pending_modification")
        if pending:
            lines.append(str(pending))
        lines.append("")
        lines += ["## Restart Log"]
        lines += [f"- {entry}" for entry in (data.get("restart_log") or [])]
        lines.append("")
        lines += ["## Settings"]
        settings = data.get("settings") or {}
        lines.append(json.dumps(settings, sort_keys=True, separators=(",", ":")))
        lines.append("")
        return "\n".join(lines)

    def _write(self, data: dict) -> None:
        """Atomic write via temp file + replace."""
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".state.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self._render(data))
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


STATE = StateTracker()

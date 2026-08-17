"""OpenCode provider adapter — the default execution runtime (Phase 5).

This adapter encapsulates the existing ``opencode run`` subprocess path that
was previously inline in ``workflow_engine._default_dispatch`` / ``run_hub``:

    opencode run --agent <agent> --auto -m <model> "<prompt>"

Behavior is preserved verbatim: the same command shape, the same stdout
collection, the same ANSI stripping, the same TLS-bypass environment opt-in,
and the same exit-code semantics. OpenCode itself owns authentication (it
reads ``~/.local/share/opencode/auth.json``) and the model-fallback plugin, so
this adapter never touches credentials.

The module-level helpers (:func:`build_run_command`, :func:`opencode_command`,
:func:`insecure_tls_env`, :func:`strip_ansi`, :func:`sanitize_prompt`) are the
canonical copies; ``run_hub`` and ``orchestrator`` import them from here so
every dispatch path shares one command builder.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from scripts.core.execution.errors import (
    AdapterCancelledError,
    AdapterError,
    AdapterTimeoutError,
)
from scripts.core.execution.schema import ModelRequest, ModelResponse

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Poll interval for timeout / cancellation checks while waiting on the child.
_POLL_SECONDS = 0.1


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a log string."""
    return _ANSI_RE.sub("", text)


def sanitize_prompt(prompt: str) -> str:
    """Strip control characters and leading whitespace from a raw prompt."""
    return _CONTROL_CHARS_RE.sub("", prompt).lstrip()


def opencode_command() -> str | None:
    """Resolve the opencode executable path (PATHEXT-aware, Windows-safe)."""
    return shutil.which("opencode") or shutil.which("opencode.cmd")


def insecure_tls_env() -> dict[str, str] | None:
    """Env override for opencode subprocesses when the TLS bypass is on.

    ``ZOVA_ALLOW_INSECURE_TLS=1`` (or ``true``/``yes``) sets
    ``NODE_TLS_REJECT_UNAUTHORIZED=0`` so the opencode CLI skips certificate
    verification. Strictly opt-in for environments with self-signed or
    intercepting certificates; default (unset or 0) leaves Node's TLS
    verification fully enabled. Returns ``None`` when disabled so subprocesses
    inherit the environment unchanged.
    """
    raw = os.environ.get("ZOVA_ALLOW_INSECURE_TLS", "").strip().lower()
    if raw not in ("1", "true", "yes"):
        return None
    return {**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "0"}


def build_run_command(exe: str, agent: str, prompt: str,
                      model: str | None = None) -> list[str]:
    """Build the ``opencode run`` argv for one agent (plain dispatch)."""
    cmd = [exe, "run", "--agent", agent, "--auto"]
    if model:
        cmd += ["-m", model]
    prompt = sanitize_prompt(prompt)
    if prompt.startswith("-"):
        cmd.append("--")
    cmd.append(prompt)
    return cmd


class OpenCodeAdapter:
    """Provider adapter that executes a request through the ``opencode`` CLI.

    This is the **default** adapter: every node whose resolved connection does
    not name a direct provider (or whose resolution degraded to the local
    runtime) executes here. Credentials are never handled by this adapter —
    opencode reads its own auth store.
    """

    provider_id = "opencode"

    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd

    def execute(
        self,
        request: ModelRequest,
        connection=None,  # ResolvedConnection — ignored (opencode owns auth)
        *,
        timeout: float | None = None,
        cancel_event: threading.Event | None = None,
        execution_id: str = "",
    ) -> ModelResponse:
        """Run one node through ``opencode run``.

        Reads stdout to completion, enforcing ``timeout`` (terminate + kill on
        expiry) and ``cancel_event`` (terminate + kill on cancellation). Never
        leaves an orphan subprocess: the child is killed and reaped before any
        failure is raised.
        """
        if not request.prompt.strip():
            raise AdapterError("node produced an empty prompt",
                               error_code="empty_prompt")
        agent = request.agent
        if not agent:
            raise AdapterError("OpenCode adapter requires metadata.agent",
                               error_code="empty_prompt")
        exe = opencode_command()
        if not exe:
            raise AdapterError(
                "opencode executable not found on PATH. Install opencode or "
                "add it to PATH.", error_code="opencode_missing")
        cmd = build_run_command(exe, agent, request.prompt, request.model)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.cwd or Path.cwd()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",  # POSIX: own process group
                env=insecure_tls_env(),
            )
        except OSError as exc:
            raise AdapterError(f"failed to launch opencode: {exc}",
                               error_code="opencode_missing") from exc

        job_handle = _assign_windows_job(proc)

        lines: list[str] = []
        started = time.monotonic()

        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    line = strip_ansi(raw.rstrip("\r\n"))
                    if line:
                        lines.append(line)
            except (OSError, ValueError):
                pass

        reader = threading.Thread(target=_reader, name="opencode-reader",
                                  daemon=True)
        reader.start()

        deadline = (started + timeout) if timeout is not None else None
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    _kill(proc)
                    raise AdapterCancelledError()
                if deadline is not None and time.monotonic() >= deadline:
                    _kill(proc)
                    raise AdapterTimeoutError(
                        f"opencode execution exceeded {timeout:g}s")
                try:
                    proc.wait(timeout=_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            reader.join(timeout=2.0)
            # A descendant can inherit the stdout pipe even after the direct
            # process has been killed.  On Windows, closing the text wrapper
            # while the reader still owns it waits on the reader's lock until
            # that descendant exits, defeating prompt cancellation.  The
            # reader is a daemon; only close synchronously once it has stopped.
            if not reader.is_alive():
                try:
                    if proc.stdout is not None:
                        proc.stdout.close()
                except OSError:
                    pass
            _close_windows_job(job_handle)

        returncode = proc.returncode
        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        if returncode != 0:
            cmd_str = " ".join(cmd)
            if len(cmd_str) > 200:
                cmd_str = cmd_str[:197] + "…"
            raise AdapterError(
                f"opencode exited with code {returncode}: {cmd_str}",
                error_code="nonzero_exit")
        return ModelResponse(
            text="\n".join(lines),
            finish_reason="stop",
            usage={},
            model=request.model,
            provider=self.provider_id,
            raw_metadata={"exit_code": returncode, "latency_ms": latency_ms},
        )


def _kill(proc: subprocess.Popen) -> None:
    """Kill the whole child process tree so nothing is left orphaned.

    On Windows an ``opencode.cmd`` shim is executed through ``cmd.exe`` which
    spawns the real command as a grandchild — killing only the direct child
    would orphan it (and hold working-directory handles). ``taskkill /T /F``
    terminates the tree; on POSIX the child runs in its own process group
    (``start_new_session``) so ``killpg`` covers the tree.
    """
    if os.name == "nt":
        job_handle = getattr(proc, "_zova_job_handle", None)
        if job_handle:
            try:
                ctypes.windll.kernel32.TerminateJobObject(job_handle, 1)
            except (AttributeError, OSError):
                pass
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            # ``taskkill`` can itself stall in constrained Windows
            # environments.  Killing the direct process is still preferable
            # to blocking cancellation indefinitely.
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.wait(timeout=5.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
            proc.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _assign_windows_job(proc: subprocess.Popen):
    """Put a Windows child in a killable job that owns its descendants."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        if not kernel32.AssignProcessToJobObject(handle, int(proc._handle)):
            kernel32.CloseHandle(handle)
            return None
        proc._zova_job_handle = handle
        return handle
    except (AttributeError, OSError, TypeError):
        return None


def _close_windows_job(handle) -> None:
    if not handle or os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        pass

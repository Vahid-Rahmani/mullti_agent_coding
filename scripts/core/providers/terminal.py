"""Small cross-platform interactive terminal process abstraction."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path


class TerminalProcess:
    """PTY-backed process with byte-preserving reads and writes."""
    def __init__(self, command: str, cwd: Path, cols: int | None = None,
                 rows: int | None = None):
        self.command, self.cwd = command, cwd
        self._lock = threading.Lock(); self._closed = False
        if (cols is None) != (rows is None):
            raise ValueError("cols and rows must be provided together")
        dimensions = None
        if cols is not None and rows is not None:
            cols = max(2, min(int(cols), 512))
            rows = max(2, min(int(rows), 256))
            dimensions = (rows, cols)
        self.initial_dimensions = (cols, rows) if dimensions else None
        if os.name == "nt":
            try:
                from winpty import PtyProcess
            except ImportError as exc:
                raise RuntimeError("FreeBuff requires the pywinpty PTY dependency on Windows") from exc
            spawn_args = {"cwd": str(cwd)}
            if dimensions is not None:
                # pywinpty expects dimensions as (rows, cols).  Supplying it
                # at spawn prevents an interactive TUI from drawing once at
                # the default 80x24 before the browser geometry arrives.
                spawn_args["dimensions"] = dimensions
            self._proc = PtyProcess.spawn(command, **spawn_args)
            self.pid = getattr(self._proc, "pid", None)
            self._winpty = True
        else:
            import pty
            import select
            self._select = select; self._master, self.pid = pty.fork()
            if self.pid == 0:
                os.chdir(cwd); os.execv(command, [command])
            self._winpty = False
            if dimensions is not None:
                self.resize(cols, rows)
    def write(self, text: str) -> None:
        with self._lock:
            if self._closed: return
            if self._winpty: self._proc.write(text)
            else: os.write(self._master, text.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        """Synchronize the child PTY dimensions with the rendered terminal."""
        cols = max(2, min(int(cols), 512))
        rows = max(2, min(int(rows), 256))
        with self._lock:
            if self._closed:
                return
            if self._winpty:
                # pywinpty expects (rows, cols); ConPTY then notifies the
                # foreground TUI so it redraws for the new viewport.
                self._proc.setwinsize(rows, cols)
            else:
                import fcntl
                import struct
                import termios
                fcntl.ioctl(self._master, termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0))
    def read_available(self, timeout: float = 0.1) -> bytes:
        if self._winpty:
            try: return self._proc.read(4096).encode("utf-8", "replace")
            except (EOFError, OSError, AttributeError): return b""
        ready, _, _ = self._select.select([self._master], [], [], timeout)
        if not ready: return b""
        try: return os.read(self._master, 4096)
        except (OSError, EOFError): return b""
    def poll(self) -> int | None:
        if self._winpty: return self._proc.exitstatus if not self._proc.isalive() else None
        pid, status = os.waitpid(self.pid, os.WNOHANG)
        return None if pid == 0 else os.waitstatus_to_exitcode(status)
    def terminate(self) -> None:
        with self._lock:
            self._closed = True
            try:
                if self._winpty:
                    # pywinpty owns the cmd.exe host, but FreeBuff is a Node
                    # grandchild of that shell.  Terminating only the PTY
                    # wrapper can leave the singleton FreeBuff process alive,
                    # so stop the complete Windows process tree first.
                    if self.pid:
                        try:
                            subprocess.run(
                                ["taskkill", "/PID", str(self.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                timeout=5.0,
                                check=False,
                            )
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                    self._proc.terminate(force=True)
                else: os.kill(self.pid, 9)
            except (OSError, ProcessLookupError, AttributeError): pass

__all__ = ["TerminalProcess"]

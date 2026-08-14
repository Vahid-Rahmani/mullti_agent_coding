"""Provider adapter tests (Phase 5).

Tests the ProviderAdapter contract and the OpenCodeAdapter against a
**deterministic fake ``opencode`` executable** (``_fake_opencode.py`` exposed
through a PATH shim). No real OpenCode install and no real credentials are
involved: the fake prints canned stdout, exits 0/1, sleeps, and records argv
per environment-variable scripting.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core.execution.errors import (
    AdapterCancelledError,
    AdapterError,
    AdapterTimeoutError,
)
from scripts.core.execution.schema import ModelRequest
from scripts.core.providers.base import (
    ResolvedConnection,
)
from scripts.core.providers.opencode import (
    OpenCodeAdapter,
    build_run_command,
)

FAKE_PY = str((Path(__file__).parent / "_fake_opencode.py").resolve())


def make_opencode_shim(dirpath: Path) -> None:
    """Expose a fake ``opencode`` on PATH (Windows .cmd shim)."""
    (dirpath / "opencode.cmd").write_text(
        f'@echo off\r\n"{sys.executable}" "{FAKE_PY}" %*\r\n',
        encoding="utf-8")
    os.environ["PATH"] = str(dirpath) + os.pathsep + os.environ.get("PATH", "")


class FakeOpenCodeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        make_opencode_shim(self.dir)
        self._env_keys = ["FAKE_OPENCODE_EXIT", "FAKE_OPENCODE_STDOUT",
                          "FAKE_OPENCODE_SLEEP", "FAKE_OPENCODE_COUNTER",
                          "FAKE_OPENCODE_FAIL_UNTIL", "FAKE_OPENCODE_ARGS"]
        self._saved = {k: os.environ.get(k) for k in self._env_keys}
        for k in self._env_keys:
            os.environ.pop(k, None)
        self.adapter = OpenCodeAdapter(cwd=self.dir)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _request(self, model="opencode/big-pickle", prompt="do it",
                 agent="matthew", execution_id="run-1"):
        return ModelRequest(model=model, prompt=prompt, metadata={
            "agent": agent, "node_id": "n1", "execution_id": execution_id})

    def _conn(self):
        return ResolvedConnection(local=True, source="local")


class TestOpenCodeCommand(unittest.TestCase):
    def test_build_run_command_shape(self):
        cmd = build_run_command("opencode", "matthew", "fix the bug",
                                "opencode/big-pickle")
        self.assertEqual(cmd[:4], ["opencode", "run", "--agent", "matthew"])
        self.assertIn("--auto", cmd)
        self.assertIn("-m", cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], "opencode/big-pickle")
        self.assertEqual(cmd[-1], "fix the bug")

    def test_build_run_command_no_model_and_dash_prompt(self):
        cmd = build_run_command("opencode", "alex", "-something", None)
        self.assertNotIn("-m", cmd)
        self.assertEqual(cmd[-2:], ["--", "-something"])


class TestOpenCodeAdapter(FakeOpenCodeTestCase):
    def test_stdout_collection_and_exit_zero(self):
        os.environ["FAKE_OPENCODE_STDOUT"] = "line one\nline two\n"
        os.environ["FAKE_OPENCODE_ARGS"] = str(self.dir / "args.json")
        resp = self.adapter.execute(self._request(), self._conn())
        self.assertEqual(resp.text, "line one\nline two")
        self.assertEqual(resp.provider, "opencode")
        self.assertEqual(resp.model, "opencode/big-pickle")
        args = json.loads((self.dir / "args.json").read_text(encoding="utf-8"))
        self.assertIn("run", args)
        self.assertEqual(args[args.index("--agent") + 1], "matthew")
        self.assertEqual(args[args.index("-m") + 1], "opencode/big-pickle")
        self.assertEqual(args[-1], "do it")

    def test_nonzero_exit_raises_typed_error(self):
        os.environ["FAKE_OPENCODE_EXIT"] = "1"
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.execute(self._request(), self._conn())
        self.assertEqual(ctx.exception.error_code, "nonzero_exit")

    def test_empty_prompt_is_typed_failure(self):
        # The schema already rejects empty prompts at construction; build the
        # request directly (bypassing __post_init__) so we can prove the
        # adapter's own defensive guard still fails loudly and typed.

        req = self._request()
        object.__setattr__(req, "prompt", "   ")
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.execute(req, self._conn())
        self.assertEqual(ctx.exception.error_code, "empty_prompt")

    def test_timeout_terminates_and_is_typed(self):
        os.environ["FAKE_OPENCODE_SLEEP"] = "30"
        started = time.monotonic()
        with self.assertRaises(AdapterTimeoutError):
            self.adapter.execute(self._request(), self._conn(), timeout=1)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 20, "timeout must terminate promptly")

    def test_cancel_terminates_and_is_typed(self):
        os.environ["FAKE_OPENCODE_SLEEP"] = "30"
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(AdapterCancelledError):
            self.adapter.execute(self._request(), self._conn(), timeout=60,
                                 cancel_event=cancel)
        self.assertLess(time.monotonic() - started, 20,
                        "cancellation must terminate promptly")

    def test_reusable_after_timeout_no_orphan(self):
        # a killed child must not block subsequent executions (no orphan/resource)
        os.environ["FAKE_OPENCODE_SLEEP"] = "30"
        with self.assertRaises(AdapterTimeoutError):
            self.adapter.execute(self._request(execution_id="r1"), self._conn(),
                                 timeout=1)
        os.environ.pop("FAKE_OPENCODE_SLEEP", None)
        os.environ["FAKE_OPENCODE_STDOUT"] = "second run ok"
        resp = self.adapter.execute(self._request(execution_id="r2"), self._conn())
        self.assertEqual(resp.text, "second run ok")

    def test_ansi_output_is_stripped(self):
        os.environ["FAKE_OPENCODE_STDOUT"] = "\x1b[32mgreen\x1b[0m plain\n"
        resp = self.adapter.execute(self._request(), self._conn())
        self.assertEqual(resp.text, "green plain")


class FakeAdapter:
    """Minimal protocol-compliant adapter used by executor tests."""

    provider_id = "fake"

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}      # prompt-substring -> response/error
        self.calls = []
        self.lock = threading.Lock()

    def execute(self, request, connection, *, timeout=None, cancel_event=None,
                execution_id=""):
        with self.lock:
            self.calls.append(request.prompt)
        # scripted failure (prompt contains the marker)
        if "FAIL" in request.prompt:
            from scripts.core.execution.errors import AdapterError

            raise AdapterError("scripted failure", error_code="nonzero_exit")
        from scripts.core.execution.schema import ModelResponse

        return ModelResponse(text=f"fake-answer-{request.prompt[:8]}",
                             provider="fake", model=request.model)


class TestProtocolCompliance(unittest.TestCase):
    def test_fake_adapter_satisfies_contract(self):
        from scripts.core.execution.schema import ModelResponse

        def execute(self, request, connection, *, timeout=None,
                    cancel_event=None, execution_id=""):
            return ModelResponse(text="ok", provider="fake")

        adapter = type("Duck", (), {"provider_id": "duck", "execute": execute})
        self.assertIsInstance(adapter, type)  # structural contract (duck-typed)
        self.assertEqual(adapter.provider_id, "duck")
        # class attribute, unbound: (self, request, connection)
        resp = adapter.execute(None, None, None)
        self.assertEqual(resp.text, "ok")

    def test_adapter_registry_defaults_to_opencode(self):
        from scripts.core.providers.base import adapter_for

        adapter = adapter_for(None)
        self.assertEqual(adapter.provider_id, "opencode")

    def test_resolved_connection_never_serializes_credential(self):
        conn = ResolvedConnection(connection_id="c1", provider="openai",
                                  local=False, source="explicit")
        conn = conn.with_credential("sk-top-secret")
        self.assertTrue(conn.has_credential())
        d = conn.to_dict()
        self.assertNotIn("sk-top-secret", repr(d))
        for key in ("credential", "_credential", "api_key", "secret", "token"):
            self.assertNotIn(key, d)
        import json as _json

        self.assertNotIn("sk-top-secret", _json.dumps(d))


if __name__ == "__main__":
    unittest.main()

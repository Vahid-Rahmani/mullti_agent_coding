"""Per-agent spec unit tests — each AgentSpec module is exercised independently.

A shared base class verifies the invariants every agent must satisfy; one
subclass per agent (M1..M7 plus the master coordinator) pins the exact
identity and configured model.

Also verifies the launcher contract: every spec's configured model must match
``opencode.json`` (the runtime OpenCode config).
"""

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import agents  # noqa: E402


def _load_spec(module_name):
    """Import a spec module by name and return its ``SPEC``."""
    return __import__(f"scripts.core.agents.{module_name}", fromlist=["SPEC"]).SPEC


class _AgentSpecTestCase(unittest.TestCase):
    """Shared invariants; subclasses pin the per-agent values.

    Abstract base: ``setUpClass`` skips it so unittest only runs the concrete
    per-agent subclasses.
    """

    module_name = ""
    tag = ""
    name = ""
    agent = ""
    model = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.module_name:
            raise unittest.SkipTest("abstract base; test via a concrete subclass")
        cls.spec = _load_spec(cls.module_name)

    def test_dedicated_module_holds_spec(self):
        self.assertIsNotNone(self.spec)

    def test_identity_fields(self):
        self.assertEqual(self.spec.tag, self.tag)
        self.assertEqual(self.spec.name, self.name)
        self.assertEqual(self.spec.agent, self.agent)

    def test_model_configured(self):
        self.assertEqual(self.spec.model, self.model)

    def test_plain_fields_only(self):
        """No specialized fields survive on any agent spec."""
        self.assertFalse(hasattr(self.spec, "modes"))
        self.assertFalse(hasattr(self.spec, "extra_modes"))
        self.assertFalse(hasattr(self.spec, "persona"))
        self.assertFalse(hasattr(self.spec, "role"))
        self.assertFalse(hasattr(self.spec, "description"))
        self.assertFalse(hasattr(self.spec, "immutable"))
        self.assertFalse(hasattr(self.spec, "pinned_model"))
        self.assertFalse(hasattr(self.spec, "pinned_mode"))

    def test_registry_consistency(self):
        self.assertIs(agents.AGENT_SPEC_BY_TAG[self.tag], self.spec)
        self.assertIs(agents.AGENT_SPEC_BY_AGENT[self.agent], self.spec)


class TestMatthewSpec(_AgentSpecTestCase):
    module_name = "matthew"
    tag = "m1"
    name = "Matthew"
    agent = "matthew"
    model = "opencode/deepseek-v4-flash-free"


class TestAlexSpec(_AgentSpecTestCase):
    module_name = "alex"
    tag = "m2"
    name = "Alex"
    agent = "alex"
    model = "opencode/deepseek-v4-flash-free"


class TestSarahSpec(_AgentSpecTestCase):
    module_name = "sarah"
    tag = "m3"
    name = "Sarah"
    agent = "sarah"
    model = "opencode/deepseek-v4-flash-free"


class TestDavidSpec(_AgentSpecTestCase):
    module_name = "david"
    tag = "m4"
    name = "David"
    agent = "david"
    model = "opencode/big-pickle"


class TestElenaSpec(_AgentSpecTestCase):
    module_name = "elena"
    tag = "m5"
    name = "Elena"
    agent = "elena"
    model = "opencode/ling-3.0-tiny-free"


class TestMaxSpec(_AgentSpecTestCase):
    module_name = "max"
    tag = "m6"
    name = "Max"
    agent = "max"
    model = "opencode/deepseek-v4-flash-free"


class TestChloeSpec(_AgentSpecTestCase):
    module_name = "chloe"
    tag = "m7"
    name = "Chloe"
    agent = "chloe"
    model = "opencode/ling-3.0-tiny-free"


class TestMasterSpec(_AgentSpecTestCase):
    """Master is the coordinator: no OpenCode agent, no model."""

    module_name = "master"
    tag = "master"
    name = "Master"
    agent = None
    model = None

    def test_no_opencode_agent(self):
        self.assertIsNone(self.spec.agent)
        self.assertIsNone(self.spec.model)

    def test_master_not_in_specialist_roster(self):
        self.assertNotIn(self.spec, agents.AGENT_SPECS)
        self.assertIs(agents.MASTER_SPEC, self.spec)

    def test_registry_consistency(self):
        # Master is the coordinator tab, not a specialist: no tag/agent lookups.
        self.assertNotIn("master", agents.AGENT_SPEC_BY_TAG)
        self.assertIs(agents.MASTER_SPEC, self.spec)


class SpecModelConsistencyTestCase(unittest.TestCase):
    """Spec models must match opencode.json so launcher, terminal, and OpenCode agree."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(Path(REPO_ROOT) / "opencode.json", encoding="utf-8") as fh:
            cls.config = json.load(fh)

    def test_every_agent_model_matches_opencode_json(self):
        for spec in agents.AGENT_SPECS:
            json_model = self.config["agent"][spec.agent]["model"]
            self.assertEqual(spec.model, json_model, spec.agent)


class SpecCliTestCase(unittest.TestCase):
    """The launcher CLI (scripts/core/agents/__main__.py) contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from scripts.core.agents import __main__ as cli

        cls.cli = cli

    def _capture(self, argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = self.cli.main(argv)
        return code, buf.getvalue(), err.getvalue()

    def test_list_prints_seven_agent_keys(self):
        code, out, _ = self._capture(["list"])
        self.assertEqual(code, 0)
        self.assertEqual(
            [ln for ln in out.splitlines() if ln.strip()],
            ["matthew", "alex", "sarah", "david", "elena", "max", "chloe"],
        )

    def test_roster_prints_slot_aligned_rows(self):
        code, out, _ = self._capture(["roster"])
        self.assertEqual(code, 0)
        rows = [row.split() for row in out.splitlines() if row.strip()]
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual(len(row), 4)  # tag agent name model
        self.assertEqual(rows[0][0], "m1")
        self.assertEqual(rows[0][1], "matthew")
        self.assertEqual(rows[3][1], "david")
        self.assertEqual(rows[3][3], "opencode/big-pickle")

    def test_model_by_key_and_tag(self):
        code, out, _ = self._capture(["model", "matthew"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "opencode/deepseek-v4-flash-free")
        code, out, _ = self._capture(["model", "m7"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "opencode/ling-3.0-tiny-free")

    def test_unknown_agent_exits_2(self):
        code, _out, err = self._capture(["model", "nobody"])
        self.assertEqual(code, 2)
        self.assertIn("unknown agent", err.lower())

    def test_unknown_command_exits_2(self):
        code, _out, _err = self._capture(["bogus"])
        self.assertEqual(code, 2)

    def test_verify_reports_in_sync(self):
        # Coupled to the live opencode.json by design: this is the drift
        # contract. A legitimate config change requires a matching spec
        # change, or this (and SpecModelConsistencyTestCase) fail on purpose.
        code, out, _ = self._capture(["verify"])
        self.assertEqual(code, 0)
        self.assertIn("in sync", out)


if __name__ == "__main__":
    unittest.main()

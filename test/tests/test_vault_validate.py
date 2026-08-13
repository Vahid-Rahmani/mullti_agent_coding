"""Dedicated tests for scripts/vault_validate.py (vault node schema validator).

Covers: frontmatter parsing (valid / missing block / unknown key /
unparseable line / blank+comment lines), node discovery (section scoping +
``_``-template exemption), WikiLink collection (code stripping), and the full
validation rules exercised through ``main()``'s exit code and output — valid
vaults pass (exit 0) while missing fields, invalid values, duplicate names,
broken references, missing parent links, and orphans each fail (exit 1).

All fixtures use temporary vaults; the real ``obsidian_vault/`` is never read.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import vault_validate as vv  # noqa: E402

# A non-root node body that satisfies the parent-link check and links back to
# the root (so the root has an inbound link and nothing is flagged orphan).
STANDARD_BODY = "↑ Parent: [[System_Core]]\n[[System_Core]]\n"


def frontmatter(ntype="system", status="active", owner="orchestrator",
                created="2026-08-11", updated="2026-08-11", **extra):
    """Render a minimal, valid frontmatter block (plus optional extra keys)."""
    lines = ["---",
             f"type: {ntype}",
             f"status: {status}",
             f"owner: {owner}",
             f"created: {created}",
             f"updated: {updated}"]
    for key, value in extra.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def node(fm, name, body):
    """Combine a frontmatter block with a heading and body."""
    return f"{fm}# {name}\n\n{body}\n"


class TestParseFrontmatter(unittest.TestCase):
    """Unit tests of the frontmatter parser (no filesystem)."""

    def test_valid_frontmatter(self):
        fields, err = vv.parse_frontmatter(frontmatter(related="[A, B]"))
        self.assertIsNone(err)
        self.assertEqual(fields["type"], "system")
        self.assertEqual(fields["status"], "active")
        self.assertEqual(fields["owner"], "orchestrator")
        self.assertEqual(fields["created"], "2026-08-11")
        self.assertEqual(fields["related"], "[A, B]")

    def test_missing_block(self):
        fields, err = vv.parse_frontmatter("# Just a heading\nbody\n")
        self.assertEqual(fields, {})
        self.assertIn("missing frontmatter block", err)

    def test_unknown_key(self):
        text = "---\ntype: system\nstatus: active\nowner: o\n" \
               "created: 2026-08-11\nupdated: 2026-08-11\nbogus: 1\n---\n\n"
        fields, err = vv.parse_frontmatter(text)
        self.assertEqual(fields, {})
        self.assertIn("unknown frontmatter key", err)
        self.assertIn("bogus", err)

    def test_unparseable_line(self):
        text = "---\ntype: system\nno colon here\n---\n\n"
        fields, err = vv.parse_frontmatter(text)
        self.assertEqual(fields, {})
        self.assertIn("unparseable frontmatter line", err)

    def test_blank_and_comment_lines_ignored(self):
        text = ("---\n"
                "type: system\n"
                "status: active\n"
                "owner: o\n"
                "created: 2026-08-11\n"
                "updated: 2026-08-11\n"
                "\n"
                "# a comment\n"
                "---\n\n")
        fields, err = vv.parse_frontmatter(text)
        self.assertIsNone(err)
        self.assertEqual(fields["type"], "system")


class TestNodeDiscovery(unittest.TestCase):
    """list_nodes: section scoping and template exemption."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_lists_only_schema_section_nodes(self):
        self.write("00-System/Real.md", "x")
        self.write("03-Tasks/Task.md", "x")
        self.write("Dashboard.md", "x")              # root file: not a section
        self.write("prompts/prompt-1.md", "x")       # legacy dir: not a section
        self.write("99-Other/Thing.md", "x")         # unknown section
        names = [p.name for p in vv.list_nodes(self.vault)]
        self.assertEqual(names, ["Real.md", "Task.md"])

    def test_template_files_exempt(self):
        self.write("00-System/_TASK_TEMPLATE.md", "garbage, no frontmatter")
        self.write("00-System/Real.md", "x")
        names = [p.name for p in vv.list_nodes(self.vault)]
        self.assertEqual(names, ["Real.md"])


class TestLinkCollection(unittest.TestCase):
    """collect_links: WikiLink extraction with code stripping."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_links_and_strips_code(self):
        path = self.dir / "a.md"
        path.write_text(
            "[[Target]] [[Other|alias]]\n"
            "```\n[[InFence]]\n```\n"
            "`[[InlineCode]]`\n",
            encoding="utf-8",
        )
        targets = vv.collect_links([path])
        self.assertEqual(targets, {"Target", "Other"})


class VaultValidateTestCase(unittest.TestCase):
    """Shared harness: a temp vault + helpers to run the full validator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_validator(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vv.main(["--vault", str(self.vault), *extra])
        return code, buf.getvalue()

    def make_valid_vault(self):
        self.write("00-System/System_Core.md",
                   node(frontmatter(), "System_Core", "[[System_Node]]\n"))
        self.write("00-System/System_Node.md",
                   node(frontmatter(), "System_Node",
                        "↑ Parent: [[System_Core]]\n"))

    def make_flawed_vault(self, fm, name="Flawed", body=STANDARD_BODY):
        """Root links to a single flawed node; both keep inbound/parent links
        so the *only* violations come from the flawed frontmatter."""
        self.write("00-System/System_Core.md",
                   node(frontmatter(), "System_Core", f"[[{name}]]\n"))
        self.write(f"00-System/{name}.md", node(fm, name, body))


class TestValidVault(VaultValidateTestCase):
    def test_valid_vault_exits_zero(self):
        self.make_valid_vault()
        code, out = self.run_validator()
        self.assertEqual(code, 0)
        self.assertIn("VAULT VALIDATION OK — 2 node(s)", out)

    def test_template_files_do_not_break_validation(self):
        self.make_valid_vault()
        self.write("00-System/_BROKEN_TEMPLATE.md", "no frontmatter at all")
        code, out = self.run_validator()
        self.assertEqual(code, 0)
        self.assertIn("2 node(s)", out)


class TestValidationRules(VaultValidateTestCase):
    """Each rule is broken in isolation and must yield exit code 1."""

    def assert_fails_with(self, out, code, fragment):
        self.assertEqual(code, 1, out)
        self.assertIn(fragment, out)
        self.assertIn("VAULT VALIDATION FAILED", out)

    def test_no_nodes_exits_one(self):
        empty = Path(self.tmp.name) / "empty_vault"
        empty.mkdir()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = vv.main(["--vault", str(empty)])
        self.assertEqual(code, 1)
        self.assertIn("no schema-managed nodes found", buf.getvalue())

    def test_missing_required_field(self):
        fm = "---\ntype: system\nowner: orchestrator\n" \
             "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n"
        self.make_flawed_vault(fm)
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "missing frontmatter field(s): status")

    def test_unknown_type(self):
        self.make_flawed_vault(frontmatter(ntype="bogus"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "unknown type 'bogus'")

    def test_type_section_mismatch(self):
        self.make_flawed_vault(frontmatter(ntype="architecture"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code,
                               "does not match its section folder (01-Architecture/)")

    def test_invalid_status(self):
        self.make_flawed_vault(frontmatter(status="bogus"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "status 'bogus' not allowed")

    def test_invalid_owner(self):
        self.make_flawed_vault(frontmatter(owner="bogus"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "owner 'bogus' not in valid owners")

    def test_invalid_date(self):
        self.make_flawed_vault(frontmatter(created="not-a-date"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "created 'not-a-date' is not YYYY-MM-DD")

    def test_unresolved_related(self):
        self.make_flawed_vault(frontmatter(related="[Missing_Node]"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code,
                               "related [Missing_Node] does not resolve to a node")

    def test_unresolved_assigned_agent(self):
        self.make_flawed_vault(frontmatter(assigned_agent="Agent_Nope"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code,
                               "assigned_agent [Agent_Nope] does not resolve to a node")

    def test_unresolved_related_component(self):
        self.make_flawed_vault(frontmatter(related_component="Component_Nope"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code,
                               "related_component [Component_Nope] does not resolve to a node")

    def test_unresolved_dependencies(self):
        self.make_flawed_vault(frontmatter(dependencies="[Dep_Nope]"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code,
                               "dependencies [Dep_Nope] does not resolve to a node")

    def test_unresolved_related_agent(self):
        self.make_flawed_vault(frontmatter(related_agent="Agent_Nope"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code,
                               "related_agent [Agent_Nope] does not resolve to a node")

    def test_invalid_priority(self):
        self.make_flawed_vault(frontmatter(priority="urgent"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "priority 'urgent' not in")

    def test_duplicate_node_name(self):
        self.write("00-System/System_Core.md",
                   node(frontmatter(), "System_Core", "[[Dup]]\n"))
        self.write("00-System/Dup.md",
                   node(frontmatter(), "Dup", STANDARD_BODY))
        self.write("02-Agents/Dup.md",
                   node(frontmatter(ntype="agent"), "Dup", STANDARD_BODY))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "duplicate node name: Dup")

    def test_missing_parent_link(self):
        # Body links back to the root (root has inbound, node has inbound) but
        # omits the required '↑ Parent:' line.
        self.make_flawed_vault(frontmatter(), body="[[System_Core]]\n")
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "missing '↑ Parent:' link")

    def test_orphan_node(self):
        # Root links to nothing; the child links to the root but nobody links
        # back to the child, so the child is orphaned (and nothing else is).
        self.write("00-System/System_Core.md",
                   node(frontmatter(), "System_Core", ""))
        self.write("00-System/Orphan.md",
                   node(frontmatter(), "Orphan", "↑ Parent: [[System_Core]]\n"))
        code, out = self.run_validator()
        self.assert_fails_with(out, code, "orphan node (no inbound links)")

    def test_related_empty_list_is_valid(self):
        # An explicit empty related list must not produce an unresolved link.
        self.write("00-System/System_Core.md",
                   node(frontmatter(), "System_Core", "[[System_Node]]\n"))
        self.write("00-System/System_Node.md",
                   node(frontmatter(related="[]"), "System_Node",
                        "↑ Parent: [[System_Core]]\n"))
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()

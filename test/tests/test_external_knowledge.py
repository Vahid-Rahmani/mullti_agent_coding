"""External knowledge & prompt intelligence tests.

Covers the provenance fields added to :class:`PromptProfile`, the adapted
external-source profiles, the new workflow templates (`seo-research`,
`security-audit`), and the source-registry reference layer. These tests verify
that adapted content is traceable to its source and that nothing invalid ships.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import prompt_library as P
from scripts.core import workflows as W

ADAPTED_PROFILE_IDS = {
    "writer-anti-slop",
    "communicator-action-first",
    "research-source-manager",
    "seo-keyword-research",
    "seo-competitive-analysis",
    "security-pentest-validator",
    "agent-workflow-planner",
}


class TestPromptProvenance(unittest.TestCase):
    def test_adapted_profiles_present_and_valid(self):
        ids = {p.id for p in P.list_prompts()}
        self.assertTrue(ADAPTED_PROFILE_IDS.issubset(ids))
        for pid in ADAPTED_PROFILE_IDS:
            profile = P.get_prompt(pid)
            self.assertEqual(P.validate_profile(profile), [], pid)
            self.assertEqual(profile.origin, "adapted", pid)
            self.assertTrue(profile.source.strip(), pid)
            self.assertTrue(profile.source_url.startswith("https://"), pid)
            self.assertTrue(profile.license.strip(), pid)
            self.assertTrue(profile.adaptation_note.strip(), pid)

    def test_original_profiles_default_to_original_origin(self):
        profile = P.get_prompt("software-engineer")
        self.assertEqual(profile.origin, "original")
        self.assertEqual(profile.source, "")
        self.assertEqual(P.validate_profile(profile), [])

    def test_origin_field_round_trips(self):
        profile = P.PromptProfile.from_dict({
            "id": "round-trip", "name": "Round Trip", "role": "researcher",
            "category": "research", "prompt": "do the thing",
            "capabilities": ["research"], "version": "1.0.0",
            "source": "example/repo", "source_url": "https://example.com/repo",
            "license": "MIT", "origin": "adapted", "adaptation_note": "adapted",
        })
        self.assertEqual(P.validate_profile(profile), [])
        back = P.PromptProfile.from_dict(profile.to_dict())
        self.assertEqual(back.source, "example/repo")
        self.assertEqual(back.origin, "adapted")
        self.assertEqual(back.to_dict()["source_url"], "https://example.com/repo")

    def test_non_original_requires_source(self):
        profile = P.PromptProfile.from_dict({
            "id": "no-source", "name": "No Source", "role": "researcher",
            "category": "research", "prompt": "do the thing",
            "capabilities": ["research"], "version": "1.0.0",
            "origin": "adapted",
        })
        problems = P.validate_profile(profile)
        self.assertTrue(any("requires a source reference" in m for m in problems))

    def test_unknown_origin_is_rejected(self):
        profile = P.PromptProfile.from_dict({
            "id": "bad-origin", "name": "Bad Origin", "role": "researcher",
            "category": "research", "prompt": "do the thing",
            "capabilities": ["research"], "version": "1.0.0",
            "origin": "stolen",
        })
        problems = P.validate_profile(profile)
        self.assertTrue(any("unknown origin" in m for m in problems))


class TestExternalWorkflowTemplates(unittest.TestCase):
    def test_seo_research_template_validates(self):
        wf = W.get_template("seo-research")
        self.assertIsNotNone(wf)
        self.assertEqual(W.validate_workflow(wf), [])
        self.assertEqual([n.id for n in wf.nodes],
                         ["keyword_research", "clustering", "competitive_analysis",
                          "content_analysis", "seo_audit"])

    def test_security_audit_template_validates_and_loops(self):
        wf = W.get_template("security-audit")
        self.assertIsNotNone(wf)
        self.assertEqual(W.validate_workflow(wf), [])
        self.assertEqual(wf.entry, ["analyze"])
        conds = {(e.source, e.target): e.condition for e in wf.edges}
        self.assertEqual(conds[("rescan", "report")], "success")
        self.assertEqual(conds[("rescan", "fix")], "failure")

    def test_new_templates_are_listed(self):
        templates = W.list_templates()
        for name in ("seo-research", "security-audit"):
            self.assertIn(name, templates)
            self.assertIsNotNone(W.get_template(name), name)


SOURCE_RECORDS = {
    "genai-agents.md": "https://github.com/NirDiamant/GenAI_Agents",
    "open-notebook.md": "https://github.com/lfnovo/open-notebook",
    "no-ai-slop.md": "https://github.com/petergyang/no-ai-slop",
    "i-have-adhd.md": "https://github.com/ayghri/i-have-adhd",
    "open-seo.md": "https://github.com/every-app/open-seo",
    "strix.md": "https://github.com/usestrix/strix",
    "book.md": "",  # unresolved source — no URL expected
}


class TestSourceRegistry(unittest.TestCase):
    def test_registry_index_lists_all_sources(self):
        index = (Path(REPO_ROOT) / "knowledge" / "sources" / "README.md")
        self.assertTrue(index.is_file(), "knowledge/sources/README.md must exist")
        text = index.read_text(encoding="utf-8")
        for slug in ("NirDiamant/GenAI_Agents", "lfnovo/open-notebook",
                     "petergyang/no-ai-slop", "ayghri/i-have-adhd",
                     "every-app/open-seo", "usestrix/strix"):
            self.assertIn(slug, text, slug)

    def test_each_source_record_has_its_url(self):
        sources_dir = Path(REPO_ROOT) / "knowledge" / "sources"
        for filename, url in SOURCE_RECORDS.items():
            record = sources_dir / filename
            self.assertTrue(record.is_file(), f"{filename} must exist")
            text = record.read_text(encoding="utf-8")
            self.assertIn("License:", text, filename)
            if url:
                self.assertIn(url, text, f"{filename} missing {url}")


if __name__ == "__main__":
    unittest.main()

"""Unit tests for scripts/intent_router.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from intent_router import (
    GREETING_AGENT,
    GREETING_PROMPT_TEMPLATE,
    Route,
    classify,
    load_rules,
    log_route,
)


class RouteTestCase(unittest.TestCase):
    """Route dataclass and as_dict()."""

    def test_as_dict_shape(self):
        route = Route(
            intent="build",
            strategy="subset",
            agents=["m4", "m6", "m7"],
            confidence=0.8,
            keywords=["implement", "api"],
        )
        self.assertEqual(
            route.as_dict(),
            {
                "intent": "build",
                "strategy": "subset",
                "agents": ["m4", "m6", "m7"],
                "confidence": 0.8,
                "keywords": ["implement", "api"],
            },
        )


class ClassifyTestCase(unittest.TestCase):
    def test_greeting_single_analyst(self):
        route = classify("Hello there!")
        self.assertEqual(route.intent, "greeting")
        self.assertEqual(route.strategy, "single")
        self.assertEqual(route.agents, ["m2"])

    def test_greeting_keywords(self):
        for prompt in [
            "hi",
            "hey",
            "thanks",
            "thank you",
            "how are you",
            "what can you do",
            "help",
            "good morning",
            "good afternoon",
            "good evening",
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify(prompt).intent, "greeting")

    def test_analyze(self):
        route = classify("Analyze the project requirements")
        self.assertEqual(route.intent, "analyze")
        self.assertEqual(route.strategy, "subset")
        self.assertEqual(route.agents, ["m2", "m1"])

    def test_design(self):
        route = classify("Design the database schema")
        self.assertEqual(route.intent, "design")
        self.assertEqual(route.agents, ["m1", "m2"])

    def test_plan(self):
        route = classify("Plan the next implementation step")
        self.assertEqual(route.intent, "plan")
        self.assertEqual(route.agents, ["m3", "m2"])

    def test_build(self):
        route = classify("implement the login API")
        self.assertEqual(route.intent, "build")
        self.assertEqual(route.agents, ["m4", "m6", "m7"])

    def test_frontend(self):
        route = classify("create a React UI for the dashboard")
        self.assertEqual(route.intent, "frontend")
        self.assertEqual(route.agents, ["m5", "m6", "m7"])

    def test_test(self):
        route = classify("write tests for the module")
        self.assertEqual(route.intent, "test")
        self.assertEqual(route.agents, ["m6", "m4"])

    def test_review(self):
        route = classify("review the changes")
        self.assertEqual(route.intent, "review")
        self.assertEqual(route.agents, ["m7", "m4"])

    def test_fallback_pipeline(self):
        route = classify("Describe something completely unrelated")
        self.assertEqual(route.intent, "pipeline")
        self.assertEqual(route.strategy, "pipeline")
        self.assertEqual(route.agents, ["m1", "m3", "m4", "m6", "m7"])
        self.assertEqual(route.keywords, [])

    def test_empty_prompt(self):
        self.assertEqual(classify("").intent, "pipeline")

    def test_whitespace_prompt(self):
        self.assertEqual(classify("   \t\n").intent, "pipeline")

    def test_case_insensitive(self):
        self.assertEqual(classify("HELLO").intent, "greeting")

    def test_matched_keywords_recorded(self):
        route = classify("hello and thanks")
        self.assertEqual(route.keywords, ["hello", "thanks"])

    def test_confidence_scales_with_matches(self):
        self.assertEqual(classify("hello").confidence, 0.6)
        self.assertEqual(classify("hello and thanks").confidence, 0.7)
        self.assertEqual(classify("Describe something completely unrelated").confidence, 0.2)


class GreetingConstantsTestCase(unittest.TestCase):
    def test_greeting_agent(self):
        self.assertEqual(GREETING_AGENT, "analyst")

    def test_greeting_template_has_prompt_placeholder(self):
        self.assertIn("{prompt}", GREETING_PROMPT_TEMPLATE)


class LogRouteTestCase(unittest.TestCase):
    def test_appends_jsonl_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "routing.jsonl"
            route = classify("hello")
            log_route("hello", route, "ok", 12.5, log_path=str(log_path))
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["prompt"], "hello")
            self.assertEqual(record["intent"], "greeting")
            self.assertEqual(record["strategy"], "single")
            self.assertEqual(record["agents"], ["m2"])
            self.assertEqual(record["confidence"], route.confidence)
            self.assertEqual(record["keywords"], ["hello"])
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["duration_ms"], 12.5)
            self.assertIn("ts", record)

    def test_multiple_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "routing.jsonl"
            log_route("hello", classify("hello"), "ok", 1.0, log_path=str(log_path))
            log_route(
                "implement the login API",
                classify("implement the login API"),
                "ok",
                2.0,
                log_path=str(log_path),
            )
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["intent"], "build")

    def test_prompt_truncated_to_200_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "routing.jsonl"
            log_route("x" * 500, classify("hello"), "ok", 1.0, log_path=str(log_path))
            record = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[0])
            self.assertEqual(len(record["prompt"]), 200)

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "nested" / "routing.jsonl"
            log_route("hello", classify("hello"), "ok", 1.0, log_path=str(log_path))
            self.assertTrue(log_path.exists())


class LoadRulesTestCase(unittest.TestCase):
    def test_default_rules(self):
        rules = load_rules()
        self.assertGreater(len(rules.rules), 0)
        self.assertEqual(rules.fallback.intent, "pipeline")
        self.assertEqual(rules.fallback.agents, ["m1", "m3", "m4", "m6", "m7"])

    def test_json_override_changes_matched_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules_path = Path(tmp) / "rules.json"
            rules_path.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "intent": "custom",
                                "strategy": "subset",
                                "agents": ["m4"],
                                "keywords": ["banana"],
                            }
                        ],
                        "fallback": {
                            "intent": "pipeline",
                            "strategy": "pipeline",
                            "agents": ["m1", "m3", "m4", "m6", "m7"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            rules = load_rules(str(rules_path))
            route = classify("banana smoothie", rules=rules)
            self.assertEqual(route.intent, "custom")
            self.assertEqual(route.agents, ["m4"])


if __name__ == "__main__":
    unittest.main()
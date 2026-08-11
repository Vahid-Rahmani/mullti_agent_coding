"""Intent routing for the MultiAgentCoding control plane.

Pure-Python keyword/regex classifier that maps a user prompt to a ``Route``
(intent + agent subset) and appends every routing decision to a JSONL log.
No network calls, no third-party dependencies.

The classifier evaluates ordered keyword rules first-match-wins:
  * ``greeting``  -> ``single``  (one fast Matthew concierge reply)
  * ``analyze`` / ``design`` / ``plan`` / ``build`` / ``frontend`` /
    ``test`` / ``review`` -> ``subset`` (2-3 agents)
  * no match -> ``pipeline`` full specialist roster (Matthew -> Alex -> Sarah ->
    David -> Elena -> Max -> Chloe)
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Workspace root = the directory the launcher was launched from (mirrors
# scripts/terminal_app.py so the routing log lands in the repo's _logs/).
PROJECT_ROOT = Path(os.getcwd())

# Agent tags referenced by routes (order matches opencode.json agents).
# Derived from the canonical roster in scripts/core/agents/ when importable;
# falls back to the static tuple so this module stays runnable standalone.
try:  # pragma: no cover - import guard for standalone execution
    from scripts.core.agents import _AGENT_TAGS as _ROSTER_TAGS
    AGENT_TAGS = tuple(_ROSTER_TAGS)
    FALLBACK_AGENTS = list(AGENT_TAGS)
except Exception:  # pragma: no cover - standalone fallback
    AGENT_TAGS = ("m1", "m2", "m3", "m4", "m5", "m6", "m7")
    FALLBACK_AGENTS = list(AGENT_TAGS)

GREETING_AGENT = "matthew"
GREETING_PROMPT_TEMPLATE = (
    "You are the front-desk concierge for MultiAgentCoding. A user greeted "
    "you with: \"{prompt}\". Reply warmly in 1-3 short sentences and briefly "
    "list what the workspace can help with: analyze, design, plan, build, "
    "test, or review."
)

FALLBACK_CONFIDENCE = 0.2

_LOG_LOCK = threading.Lock()
_PROMPT_TRUNCATE = 200


@dataclass
class Rule:
    """One routing rule: if a keyword matches, route to ``agents``."""

    intent: str
    strategy: str
    agents: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class Rules:
    """Ordered routing rules plus the pipeline fallback route."""

    rules: list[Rule] = field(default_factory=list)
    fallback: Rule = field(default_factory=lambda: Rule("pipeline", "pipeline", list(FALLBACK_AGENTS), []))

    @classmethod
    def default(cls) -> "Rules":
        return cls(rules=list(DEFAULT_RULES))

    @classmethod
    def from_dict(cls, data: dict) -> "Rules":
        rules = [
            Rule(
                intent=item["intent"],
                strategy=item.get("strategy", "subset"),
                agents=list(item.get("agents", [])),
                keywords=list(item.get("keywords", [])),
            )
            for item in data.get("rules", [])
        ]
        fb = data.get("fallback", {})
        fallback = Rule(
            intent=fb.get("intent", "pipeline"),
            strategy=fb.get("strategy", "pipeline"),
            agents=list(fb.get("agents", FALLBACK_AGENTS)),
            keywords=list(fb.get("keywords", [])),
        )
        return cls(rules=rules, fallback=fallback)


DEFAULT_RULES: list[Rule] = [
    Rule(
        "greeting",
        "single",
        ["m1"],
        [
            "hello", "hi", "hey", "thanks", "thank you", "how are you",
            "what can you do", "help", "good morning", "good afternoon",
            "good evening",
        ],
    ),
    Rule(
        "self-evolve",
        "subset",
        ["m2", "m6", "m7"],
        ["upgrade", "self-evolve", "self-heal", "evolve", "heal"],
    ),
    Rule(
        "analyze",
        "subset",
        ["m1", "m2"],
        ["analyze", "analysis", "requirements", "requirement", "assess", "evaluate"],
    ),
    Rule(
        "design",
        "subset",
        ["m1", "m3"],
        ["design", "architecture", "architect", "schema", "blueprint", "model"],
    ),
    Rule(
        "plan",
        "subset",
        ["m1", "m2"],
        ["plan", "planning", "roadmap", "schedule", "milestone", "next step", "steps"],
    ),
    Rule(
        "build",
        "subset",
        ["m2", "m6", "m7"],
        [
            "build", "implement", "code", "develop", "backend", "api", "fix",
            "bug", "login", "database", "auth", "server", "endpoint",
            "function", "feature",
        ],
    ),
    Rule(
        "frontend",
        "subset",
        ["m3", "m6", "m7"],
        [
            "frontend", "front-end", "ui", "ux", "interface", "css", "html",
            "react", "component", "page", "layout", "web",
        ],
    ),
    Rule(
        "test",
        "subset",
        ["m4", "m2"],
        ["test", "tests", "testing", "unittest", "pytest", "coverage"],
    ),
    Rule(
        "review",
        "subset",
        ["m5", "m2"],
        ["review", "reviewer", "code review", "approve", "merge", "critique", "pull request", "security"],
    ),
]


@dataclass
class Route:
    """Decision for one prompt: which intent, strategy and agents to run."""

    intent: str
    strategy: str
    agents: list[str] = field(default_factory=list)
    confidence: float = 0.0
    keywords: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "intent": self.intent,
            "strategy": self.strategy,
            "agents": list(self.agents),
            "confidence": self.confidence,
            "keywords": list(self.keywords),
        }


def load_rules(path: str | os.PathLike | None = None) -> Rules:
    """Return routing rules, optionally overridden by a JSON file.

    The JSON shape is ``{"rules": [{intent, strategy, agents, keywords}],
    "fallback": {intent, strategy, agents}}``. With no ``path`` the built-in
    ``DEFAULT_RULES`` are returned.
    """
    if path is None:
        return Rules.default()
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Rules.from_dict(data)


def _keyword_matches(keyword: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _confidence(matched: list[str]) -> float:
    return round(min(1.0, 0.5 + 0.1 * len(matched)), 2)


def classify(prompt: str, rules: Rules | None = None) -> Route:
    """Classify ``prompt`` into a ``Route`` using keyword scoring.

    Ordered first-match-wins: the first rule whose keywords appear in the
    prompt wins. Prompts with no keyword match fall back to the ``pipeline``
    route (core agent subset, low confidence).
    """
    rules = rules if rules is not None else load_rules()
    text = prompt.strip().lower()
    for rule in rules.rules:
        matched = [kw for kw in rule.keywords if _keyword_matches(kw, text)]
        if matched:
            return Route(
                intent=rule.intent,
                strategy=rule.strategy,
                agents=list(rule.agents),
                confidence=_confidence(matched),
                keywords=matched,
            )
    return Route(
        intent=rules.fallback.intent,
        strategy=rules.fallback.strategy,
        agents=list(rules.fallback.agents),
        confidence=FALLBACK_CONFIDENCE,
        keywords=[],
    )


def log_route(
    prompt: str,
    route: Route,
    status: str,
    duration_ms: float,
    log_path: str | os.PathLike | None = None,
) -> None:
    """Append one JSONL routing record to ``_logs/routing.jsonl``.

    Writes are serialized with a module lock (thread-safe) and the target
    directory is created on demand. ``log_path`` overrides the default
    ``PROJECT_ROOT/_logs/routing.jsonl`` (used by tests).
    """
    path = Path(log_path) if log_path is not None else PROJECT_ROOT / "_logs" / "routing.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt[:_PROMPT_TRUNCATE],
        "intent": route.intent,
        "strategy": route.strategy,
        "agents": list(route.agents),
        "confidence": route.confidence,
        "keywords": list(route.keywords),
        "status": status,
        "duration_ms": duration_ms,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

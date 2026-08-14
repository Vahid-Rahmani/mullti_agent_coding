"""Task classification layer — deterministic, keyword-based (no LLM).

A ``TaskProfile`` describes *what a task is* (category, capabilities,
complexity, risk) so the recommendation layer can map a task → role → prompt
profile → model requirements. Everything here is plain keyword/capability
matching: the same input always yields the same output.
"""

from __future__ import annotations

from dataclasses import dataclass

# Task categories. These align closely with prompt ``CATEGORIES``; ``planning``
# maps to the project-manager prompt category ("management"), and ``general``
# matches nothing specifically.
TASK_CATEGORIES: tuple[str, ...] = (
    "development",
    "architecture",
    "debugging",
    "review",
    "testing",
    "security",
    "devops",
    "cloud",
    "data",
    "ai",
    "research",
    "documentation",
    "planning",
    "orchestration",
    "general",
)

LEVELS: tuple[str, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class TaskProfile:
    """A deterministic classification of a task.

    ``context`` carries the original free-text description (when provided);
    the other fields are the classification the recommendation layer consumes.
    """

    category: str = "general"            # one of TASK_CATEGORIES
    capabilities: tuple[str, ...] = ()    # capability vocabulary
    complexity: str = "medium"            # low | medium | high
    risk: str = "medium"                  # low | medium | high
    context: str = ""                     # original task description (optional)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "capabilities": list(self.capabilities),
            "complexity": self.complexity,
            "risk": self.risk,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "TaskProfile":
        data = data or {}
        return cls(
            category=str(data.get("category") or "general"),
            capabilities=tuple(str(x) for x in (data.get("capabilities") or [])),
            complexity=str(data.get("complexity") or "medium"),
            risk=str(data.get("risk") or "medium"),
            context=str(data.get("context") or data.get("description") or ""),
        )


# ---------------------------------------------------------------- normalization


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace for keyword matching."""
    return " ".join((text or "").lower().split())


# ---------------------------------------------------------------- category rules

# Ordered, most-specific first. Each category maps to its primary prompt role
# and a list of keyword fragments; multi-word keywords weight more during
# role inference (see ``suggest_roles_for_task``).
_CATEGORY_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("architecture", "software_architect", (
        "architect", "architecture", "system design", "design")),
    ("review", "code_reviewer", (
        "code review", "review code", "find bug", "review", "reviewer")),
    ("debugging", "debugger", (
        "debug", "root cause", "diagnose", "fix bug", "error", "stack trace")),
    ("testing", "qa_engineer", (
        "e2e", "end-to-end", "end to end", "test", "qa", "regression", "test case")),
    ("security", "security_engineer", (
        "security", "vulnerab", "threat", "auth", "exploit", "injection",
        "audit", "penetration", "attack surface", "trust boundar")),
    ("cloud", "cloud_engineer", (
        "cloud", "azure", "aws", "gcp", "network", "networking", "vpc", "dns")),
    ("devops", "devops_engineer", (
        "devops", "ci/cd", "cicd", "ci cd", "deploy", "release", "rollout",
        "infrastructure", "provision")),
    ("data", "data_engineer", (
        "data pipeline", "data", "etl", "data quality", "warehouse",
        "data validation")),
    ("ai", "ai_engineer", (
        "llm", "rag", "ai agent", "agent", "machine learning", "prompt",
        "embedding", "retrieval", "vector", "language model", "ai")),
    ("research", "researcher", (
        "research", "researcher", "survey", "literature", "investigate",
        "compare", "analyst")),
    ("documentation", "technical_writer", (
        "documentation", "document", "readme", "technical writing",
        "write doc", "guide", "docs")),
    ("planning", "project_manager", (
        "project planning", "plan", "planning", "roadmap", "milestone",
        "scope", "delivery", "risk management", "risk")),
    ("orchestration", "orchestrator", (
        "multi-agent", "orchestrat", "coordinator", "workflow", "delegat",
        "handoff", "agent coordination")),
    ("development", "software_engineer", (
        "implement", "develop", "code", "coding", "feature", "refactor",
        "software", "write code", "bug fix")),
)

# category -> default capabilities (aligned with the prompt profile vocabulary)
_CATEGORY_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "development": ("coding", "maintainability"),
    "architecture": ("architecture", "system design", "tradeoff analysis"),
    "debugging": ("debugging", "root cause analysis", "diagnosis"),
    "review": ("code review", "bug detection", "maintainability"),
    "testing": ("testing", "test design", "regression"),
    "security": ("security", "vulnerability analysis", "secure coding"),
    "devops": ("CI/CD", "automation", "deployment", "observability"),
    "cloud": ("cloud", "infrastructure", "networking"),
    "data": ("ETL", "pipelines", "data validation", "data quality"),
    "ai": ("LLM", "agents", "RAG", "evaluation"),
    "research": ("research", "evidence analysis", "synthesis"),
    "documentation": ("documentation", "technical writing", "clarity"),
    "planning": ("planning", "decomposition", "dependencies"),
    "orchestration": ("orchestration", "delegation", "agent coordination"),
    "general": (),
}

# Extra keyword-derived capabilities (ordered; more specific first). These add
# finer-grained signals on top of the category defaults, e.g. a security task
# that mentions "review"/"audit" also carries the "audit" capability.
_CAPABILITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("audit", ("audit", "review")),
    ("threat modeling", ("threat", "trust boundar", "threat model")),
    ("secure coding", ("secure", "harden", "least privilege")),
    ("vulnerability analysis", ("vulnerab", "exploit", "injection", "attack surface")),
    ("E2E", ("e2e", "end-to-end", "end to end")),
    ("root cause analysis", ("root cause", "diagnose")),
    ("code review", ("code review", "review code", "find bug", "diff")),
    ("architecture", ("architect", "architecture", "system design")),
    ("CI/CD", ("ci/cd", "cicd", "ci cd", "build pipeline")),
    ("deployment", ("deploy", "release", "rollout")),
    ("RAG", ("rag", "retrieval", "embedding", "vector")),
    ("LLM", ("llm", "language model", "prompt", "token")),
    ("agents", ("agent", "multi-agent", "autonomous")),
    ("research", ("research", "researcher", "survey", "literature", "investigate")),
    ("documentation", ("document", "documentation", "readme", "guide")),
    ("planning", ("plan", "planning", "roadmap", "milestone", "scope")),
    ("risk management", ("risk", "mitigat", "contingen")),
    ("orchestration", ("orchestrat", "coordinator", "workflow", "delegat")),
)

# Built-in task keyword → prompt id (Phase 2 mappings, most specific first).
# A substring match on the normalized task text boosts that prompt directly.
_TASK_KEYWORD_PROMPTS: tuple[tuple[str, str], ...] = (
    ("multi-agent workflow", "orchestrator-multi-agent"),
    ("agent coordination", "orchestrator-multi-agent"),
    ("task decompos", "orchestrator-task-decomposer"),
    ("workflow coordinat", "orchestrator-workflow"),
    ("azure infrastructure", "cloud-azure"),
    ("cloud architecture review", "cloud-architecture-reviewer"),
    ("data pipeline", "data-pipeline-engineer"),
    ("data quality", "data-quality-engineer"),
    ("etl", "data-etl-engineer"),
    ("threat model", "security-threat-modeler"),
    ("security audit", "security-auditor"),
    ("application security", "security-appsec-engineer"),
    ("e2e test", "qa-e2e-engineer"),
    ("test strategy", "qa-test-strategy"),
    ("write test", "qa-test-engineer"),
    ("unit test", "qa-test-engineer"),
    ("ci/cd", "devops-cicd"),
    ("cicd", "devops-cicd"),
    ("deployment", "devops-deployment"),
    ("infrastructure", "devops-infrastructure"),
    ("project planning", "pm-delivery"),
    ("risk manager", "pm-risk"),
    ("risk management", "pm-risk"),
    ("roadmap", "pm-delivery"),
    ("refactor", "software-engineer-production"),
    ("implement feature", "software-engineer-expert"),
    ("write code", "software-engineer"),
    ("debug", "debugger-root-cause"),
    ("root cause", "debugger-root-cause"),
    ("incident", "debugger-incident"),
    ("adversarial", "debugger-adversarial"),
    ("performance review", "code-reviewer-performance"),
    ("security review", "code-reviewer-security"),
    ("find bug", "code-reviewer"),
    ("code review", "code-reviewer"),
    ("rag", "ai-llm-engineer"),
    ("llm", "ai-llm-engineer"),
    ("ai agent", "ai-agent-engineer"),
    ("agent engineer", "ai-agent-engineer"),
    ("research", "researcher-technical"),
    ("literature", "researcher-literature"),
    ("documentation", "writer-documentation"),
    ("readme", "writer-readme"),
    ("doc review", "writer-docs-reviewer"),
    ("design architecture", "system-architect"),
    ("distributed", "distributed-systems-architect"),
    ("architecture review", "architecture-reviewer"),
)

_COMPLEXITY_HIGH = ("complex", "large scale", "distributed", "enterprise",
                    "critical", "high performance", "scalab", "real-time")
_COMPLEXITY_LOW = ("simple", "quick", "small", "basic", "minor", "trivial")

_RISK_HIGH = ("production", "security", "vulnerab", "critical", "incident",
              "auth", "sensitive", "pii", "payment", "financial")
_RISK_LOW = ("documentation", "readme", "comment", "format", "cosmetic")


# ---------------------------------------------------------------- classification


def classify_task(text: str) -> TaskProfile:
    """Classify free-form task text into a deterministic :class:`TaskProfile`."""
    norm = normalize(text)
    category = _classify_category(norm)
    caps = _classify_capabilities(norm, category)
    return TaskProfile(
        category=category,
        capabilities=tuple(caps),
        complexity=_classify_level(norm, _COMPLEXITY_HIGH, _COMPLEXITY_LOW),
        risk=_classify_level(norm, _RISK_HIGH, _RISK_LOW),
        context=text.strip(),
    )


def _classify_category(norm: str) -> str:
    # Weight by keyword specificity (multi-word keywords count more), so e.g.
    # "review ... for vulnerabilities" resolves to security (2 signals) over
    # review (1 signal).
    best_category = "general"
    best_score = 0
    for category, _role, keywords in _CATEGORY_RULES:
        score = sum(len(kw.split()) for kw in keywords if kw in norm)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


def _classify_capabilities(norm: str, category: str) -> list[str]:
    caps: list[str] = []
    for cap in _CATEGORY_CAPABILITIES.get(category, ()):
        caps.append(cap)
    for cap, keywords in _CAPABILITY_KEYWORDS:
        if any(kw in norm for kw in keywords) and cap not in caps:
            caps.append(cap)
    return caps


def _classify_level(norm: str, high: tuple[str, ...], low: tuple[str, ...]) -> str:
    if any(kw in norm for kw in high):
        return "high"
    if any(kw in norm for kw in low):
        return "low"
    return "medium"


# ---------------------------------------------------------------- role suggestion


def suggest_roles_for_task(task: str | TaskProfile) -> list[str]:
    """Deterministically suggest prompt roles for a task (ranked, most relevant first).

    Accepts free text (classified on the fly) or an already-built
    :class:`TaskProfile`. Returns prompt role ids (e.g. ``security_engineer``),
    ``[]`` when nothing maps.
    """
    if isinstance(task, str):
        norm = normalize(task)
    else:
        norm = normalize(task.context)
        # When a TaskProfile is given, trust its category as the primary signal.
        for category, role, _keywords in _CATEGORY_RULES:
            if category == task.category:
                return _rank_roles(norm, primary_role=role)
        return []

    return _rank_roles(norm, primary_role=None)


def _rank_roles(norm: str, primary_role: str | None) -> list[str]:
    scores: dict[str, int] = {}
    if primary_role:
        scores[primary_role] = 1000  # explicit primary role always ranks first
    for category, role, keywords in _CATEGORY_RULES:
        weight = sum(len(kw.split()) for kw in keywords if kw in norm)
        if weight:
            scores[role] = scores.get(role, 0) + weight
    return [role for role, _score in sorted(scores.items(), key=lambda kv: -kv[1])]


def category_primary_role(category: str) -> str | None:
    for cat, role, _keywords in _CATEGORY_RULES:
        if cat == category:
            return role
    return None


def task_keyword_prompt_ids(text: str) -> list[tuple[str, str]]:
    """Return the built-in ``(keyword, prompt_id)`` matches for a task string."""
    norm = normalize(text)
    out: list[tuple[str, str]] = []
    for keyword, prompt_id in _TASK_KEYWORD_PROMPTS:
        if keyword in norm:
            out.append((keyword, prompt_id))
    return out


__all__ = [
    "TaskProfile",
    "TASK_CATEGORIES",
    "LEVELS",
    "normalize",
    "classify_task",
    "suggest_roles_for_task",
    "category_primary_role",
    "task_keyword_prompt_ids",
]

"""Skill registry — lightweight native reusable capabilities.

A :class:`Skill` sits between a *role* (reusable expertise) and a *prompt
profile* / *workflow* (the execution layer). Unlike a prompt profile — which is
a long "how to think" instruction — a Skill is an **operating procedure**: an
ordered, deterministic sequence of steps plus the capabilities it provides. It
is:

    * model-independent (never references a model id)
    * agent-independent (never references an agent key)
    * reusable + composable (referenced by id from workflow nodes, and may
      optionally compose a Prompt Profile for its "how to think" text)
    * explicitly identifiable (stable slug ids)
    * provenance-aware (adapted skills carry source/license/origin, exactly like
      :class:`~scripts.core.prompt_library.schema.PromptProfile`)

Skills are **built-in data** (like prompt profiles), not per-user config (like
roles.json). Nothing here introduces a runtime dependency on any external
repository — adapted skills are written in MultiAgentCoding's own words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.core.prompt_library.schema import ORIGINS

# The coarse groupings a skill may declare. Kept small and distinct from prompt
# categories: a skill is a procedure, a prompt profile is a mindset.
SKILL_CATEGORIES: tuple[str, ...] = (
    "research",
    "quality",
    "communication",
    "seo",
    "security",
    "engineering",
    "orchestration",
    "knowledge",
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class SkillError(ValueError):
    """Raised for an unknown skill id (mapped to HTTP 404 by routes)."""


@dataclass(frozen=True)
class Skill:
    """One immutable, validated reusable capability / operating procedure."""

    id: str
    name: str
    description: str = ""
    category: str = ""                 # one of SKILL_CATEGORIES
    steps: tuple[str, ...] = ()        # the ordered operating procedure
    capabilities: tuple[str, ...] = ()
    prompt_profile: str = ""           # optional composed prompt-library id
    tags: tuple[str, ...] = ()
    version: str = "1.0.0"
    # Provenance — same style as PromptProfile.
    source: str = ""                   # upstream reference (e.g. "usestrix/strix")
    source_url: str = ""               # upstream URL
    license: str = ""                  # upstream license (e.g. "Apache-2.0")
    origin: str = "original"           # original | adapted | source-derived
    adaptation_note: str = ""          # how this skill relates to the source

    @classmethod
    def from_dict(cls, data: dict) -> Skill:
        def _list(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            return tuple(str(x) for x in value)

        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            category=str(data.get("category") or ""),
            steps=_list("steps"),
            capabilities=_list("capabilities"),
            prompt_profile=str(data.get("prompt_profile") or ""),
            tags=_list("tags"),
            version=str(data.get("version") or "1.0.0"),
            source=str(data.get("source") or ""),
            source_url=str(data.get("source_url") or ""),
            license=str(data.get("license") or ""),
            origin=str(data.get("origin") or "original"),
            adaptation_note=str(data.get("adaptation_note") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "steps": list(self.steps),
            "capabilities": list(self.capabilities),
            "prompt_profile": self.prompt_profile,
            "tags": list(self.tags),
            "version": self.version,
            "source": self.source,
            "source_url": self.source_url,
            "license": self.license,
            "origin": self.origin,
            "adaptation_note": self.adaptation_note,
        }


def validate_skill(skill: Skill) -> list[str]:
    """Return human-readable validation problems (empty == valid).

    Enforces: a slug id, a non-empty name, at least one procedure step (this is
    what distinguishes a Skill from a mere prompt), a known category, a semver
    version, and provenance rules identical to ``validate_profile`` (non-original
    skills require a source reference).
    """
    problems: list[str] = []
    if not skill.id:
        problems.append("id is required")
    elif not _SLUG_RE.match(skill.id):
        problems.append(f"invalid id {skill.id!r} (use [a-z0-9._-])")
    if not skill.name.strip():
        problems.append(f"{skill.id or '?'}: name is required")
    if not skill.steps:
        problems.append(f"{skill.id or '?'}: at least one procedure step is required")
    if skill.category not in SKILL_CATEGORIES:
        problems.append(f"{skill.id or '?'}: unknown category {skill.category!r}")
    if not skill.version or not _VERSION_RE.match(skill.version):
        problems.append(f"{skill.id or '?'}: invalid version {skill.version!r} "
                        "(use semver like 1.0.0)")
    if skill.origin not in ORIGINS:
        problems.append(f"{skill.id or '?'}: unknown origin {skill.origin!r}")
    if skill.origin != "original" and not skill.source.strip():
        problems.append(f"{skill.id or '?'}: origin {skill.origin!r} "
                        "requires a source reference")
    return problems


# ---------------------------------------------------------------- built-in skills


class SkillLibraryError(ValueError):
    """Raised for a malformed or duplicate built-in skill (a programming error)."""


def _build() -> tuple[Skill, ...]:
    built: list[Skill] = []
    seen: set[str] = set()
    for raw in BUILTIN_SKILL_DICTS:
        skill = Skill.from_dict(raw)
        problems = validate_skill(skill)
        if problems:
            raise SkillLibraryError(
                f"invalid built-in skill: {'; '.join(problems)}"
            )
        if skill.id in seen:
            raise SkillLibraryError(f"duplicate skill id {skill.id!r}")
        seen.add(skill.id)
        built.append(skill)
    return tuple(built)


BUILTIN_SKILLS: tuple[Skill, ...] = ()
_SKILLS: dict[str, Skill] = {}


def list_skills() -> list[Skill]:
    """All built-in skills, deterministically ordered by id."""
    return sorted(_SKILLS.values(), key=lambda s: s.id)


def get_skill(skill_id: str) -> Skill:
    """Return one skill by id, or raise :class:`SkillError` for an unknown id."""
    skill = _SKILLS.get((skill_id or "").strip())
    if skill is None:
        raise SkillError(f"unknown skill {skill_id!r}")
    return skill


def list_skills_by_category(category: str) -> list[Skill]:
    """Skills whose ``category`` equals ``category`` (exact match)."""
    category = (category or "").strip()
    return [s for s in list_skills() if s.category == category]


def resolve_skill_prompt(skill: Skill):
    """The composed Prompt Profile for a skill (or ``None``).

    A skill's ``prompt_profile`` is optional; when set it supplies the "how to
    think" text the skill's procedure is applied to. Resolved lazily so the
    skills module keeps no import-time coupling beyond the provenance schema.
    """
    if not skill.prompt_profile:
        return None
    from scripts.core import prompt_library

    try:
        return prompt_library.get_prompt(skill.prompt_profile)
    except prompt_library.PromptError:
        return None


def render_skill_context(skill_ids: list[str] | tuple[str, ...] | None) -> str:
    """Build a prompt-injectable Markdown block for a set of skills.

    Returns ``""`` when the list is empty or every id is unknown. Deterministic
    and idempotent; unknown ids degrade to nothing rather than raising.
    """
    ids = [str(s) for s in (skill_ids or ()) if str(s).strip()]
    if not ids:
        return ""
    skills = []
    seen: set[str] = set()
    for sid in ids:
        if sid in seen:
            continue
        seen.add(sid)
        try:
            skills.append(get_skill(sid))
        except SkillError:
            continue
    if not skills:
        return ""

    blocks = []
    for skill in skills:
        parts = [f"### {skill.name}"]
        if skill.description:
            parts.append(skill.description)
        parts.append("Procedure:")
        parts.append("".join(f"{i + 1}. {step}\n" for i, step in enumerate(skill.steps)))
        blocks.append("\n".join(parts))
    return "## Skills\n" + "\n".join(blocks) + "\n"


# ---------------------------------------------------------------- task mapping


def _norm(value: str) -> str:
    return " ".join((value or "").lower().replace("_", " ").replace("-", " ").split())


# Keyword -> skill id, ordered most-specific first (mirrors the prompt library's
# deterministic, keyword-based mapping — no LLM).
_SKILL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source-verification", ("verif", "citation", "cite", "provenance", "source check")),
    ("knowledge-extraction", ("knowledge extraction", "distill", "skill author",
                              "book to skill", "convert document", "framework mining")),
    ("structured-research", ("research", "source collection", "collect source",
                             "sources", "literature", "survey")),
    ("anti-slop-refinement", ("slop", "refine", "edit", "polish", "rewrite")),
    ("action-first-communication", ("action-first", "concise", "communicat")),
    ("competitive-analysis", ("competitor", "competitive", "gap analysis")),
    ("seo-research", ("seo", "keyword", "search intent", "ranking")),
    ("security-reconnaissance", ("recon", "attack surface", "scope", "enumerat")),
    ("security-validation", ("validate", "proof-of-concept", "poc", "pentest",
                             "vulnerab", "finding")),
    ("fix-verify-loop", ("re-scan", "rescan", "remediat", "fix", "verify fix")),
    ("repository-analysis", ("repository", "codebase", "inspect", "audit code",
                             "architecture review")),
    ("workflow-planning", ("multi-agent", "orchestrat", "workflow", "planning",
                           "delegat", "handoff")),
)


def suggest_skills_for_task(text: str) -> list[Skill]:
    """Deterministically suggest skills for a task string (keyword mapping).

    Returns skills whose keywords appear in the normalized text, most specific
    first. ``[]`` when nothing matches. No LLM, no embeddings.
    """
    key = _norm(text)
    if not key:
        return []
    out: list[Skill] = []
    seen: set[str] = set()
    for skill_id, keywords in _SKILL_KEYWORDS:
        if any(kw in key for kw in keywords):
            try:
                skill = get_skill(skill_id)
            except SkillError:
                continue
            if skill.id not in seen:
                seen.add(skill.id)
                out.append(skill)
    return out


# ---------------------------------------------------------------- built-in data

# Adapted skills are written in MultiAgentCoding's own words (never copied) and
# carry provenance so original and adapted skills stay distinguishable. See
# ``knowledge/sources/README.md`` for the license matrix.
BUILTIN_SKILL_DICTS: tuple[dict, ...] = (
    {
        "id": "structured-research",
        "name": "Structured Research",
        "description": "Collect, organize, and cite sources so findings are reusable and verifiable.",
        "category": "research",
        "steps": (
            "Define the question and the acceptance criteria before collecting anything.",
            "Capture provenance for every source: title, venue, URL, access date, license.",
            "Separate each source's actual claim from your interpretation; quote or paraphrase with a citation.",
            "Organize sources by topic and question so they can be reused, not re-collected.",
            "Synthesize with per-point citations and flag gaps: what is assumed, missing, or unverified.",
        ),
        "capabilities": ("research", "source management", "citation", "provenance"),
        "prompt_profile": "research-source-manager",
        "tags": ("research", "sources", "citations"),
        "version": "1.0.0",
        "source": "lfnovo/open-notebook",
        "source_url": "https://github.com/lfnovo/open-notebook",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Source-management and citation discipline adapted from the open-notebook research model; no code copied.",
    },
    {
        "id": "source-verification",
        "name": "Source Verification",
        "description": "Check that every claim traces to a source and distinguish fact from interpretation.",
        "category": "research",
        "steps": (
            "For each claim, identify the exact source (and quote) that supports it.",
            "Separate what the source states from what you inferred; never merge them.",
            "Flag any claim that cannot be traced to a source as unverified.",
            "Note contradictions between sources rather than silently picking one.",
            "Deliver a verification pass: verified, partially verified, and unverified claims.",
        ),
        "capabilities": ("verification", "citation", "fact-checking"),
        "prompt_profile": "research-source-manager",
        "tags": ("verification", "sources", "fact-checking"),
        "version": "1.0.0",
        "source": "lfnovo/open-notebook",
        "source_url": "https://github.com/lfnovo/open-notebook",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Claim-versus-interpretation separation adapted from the open-notebook citation model; no code copied.",
    },
    {
        "id": "anti-slop-refinement",
        "name": "Anti-Slop Refinement",
        "description": "Remove formulaic AI-writing patterns while preserving the author's voice.",
        "category": "quality",
        "steps": (
            "Cut filler: empty intensifiers, throat-clearing openings, and restated summaries.",
            "Replace formulaic transitions and canned conclusions with specific, tied-to-the-point sentences.",
            "Prefer concrete nouns, numbers, and examples over abstract generalities.",
            "Vary sentence length and structure; delete redundant hedging.",
            "Preserve the author's style, terminology, and intent — remove mechanical patterns only.",
            "Self-check that the result reads as a knowledgeable human wrote it, then list what was removed and why.",
        ),
        "capabilities": ("editing", "clarity", "self-review"),
        "prompt_profile": "writer-anti-slop",
        "tags": ("writing", "editing", "quality"),
        "version": "1.0.0",
        "source": "petergyang/no-ai-slop",
        "source_url": "https://github.com/petergyang/no-ai-slop",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Output-quality rules adapted into a native procedure; no upstream text copied.",
    },
    {
        "id": "action-first-communication",
        "name": "Action-First Communication",
        "description": "Lead with the result and next action; concise, numbered, no buried conclusions.",
        "category": "communication",
        "steps": (
            "Put the answer, change, or next action first — before background or theory.",
            "Use numbered steps for any sequence; one clear action per step.",
            "Cut explanations and tangents that do not change what the reader does.",
            "Reference the task and prior decisions so state is never re-derived.",
            "Break long tasks into small numbered increments; end with the single next action.",
        ),
        "capabilities": ("communication", "task decomposition", "concise output"),
        "prompt_profile": "communicator-action-first",
        "tags": ("communication", "action-first", "concise"),
        "version": "1.0.0",
        "source": "ayghri/i-have-adhd",
        "source_url": "https://github.com/ayghri/i-have-adhd",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Action-first / numbered-output conventions adapted into a native procedure; no upstream text copied.",
    },
    {
        "id": "seo-research",
        "name": "SEO Keyword Research",
        "description": "Build a defensible keyword set by intent, difficulty, and opportunity.",
        "category": "seo",
        "steps": (
            "Start from the site's topic and audience, then expand seed terms into related and long-tail keywords.",
            "Classify each keyword by search intent (informational, navigational, transactional, commercial).",
            "Estimate difficulty and opportunity; prefer keywords the site can realistically rank for now.",
            "Group overlapping terms into clusters so one page targets a cluster, not thin competing pages.",
            "Deliver a prioritized table (term, intent, difficulty, opportunity) with a rationale per cluster.",
        ),
        "capabilities": ("seo", "keyword research", "search intent"),
        "prompt_profile": "seo-keyword-research",
        "tags": ("seo", "keywords", "research"),
        "version": "1.0.0",
        "source": "every-app/open-seo",
        "source_url": "https://github.com/every-app/open-seo",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Keyword-research methodology distilled from the OpenSEO skill set; no upstream code or prompts copied.",
    },
    {
        "id": "competitive-analysis",
        "name": "Competitive Analysis",
        "description": "Turn competitor pages into a ranked list of gaps you can close.",
        "category": "seo",
        "steps": (
            "For each target query, identify the pages that rank and their content type, depth, and intent coverage.",
            "Assess on-page signals: title/headings, structure, freshness, authority, and intent fit.",
            "Identify what competitors do well that you do not, and what they leave uncovered (the gap).",
            "Prioritize gaps by realistic winnability: intent fit, authority, and content effort.",
            "Deliver a competitor matrix, the gap list, and one concrete action per high-value gap.",
        ),
        "capabilities": ("seo", "competitive analysis", "gap analysis"),
        "prompt_profile": "seo-competitive-analysis",
        "tags": ("seo", "competition", "analysis"),
        "version": "1.0.0",
        "source": "every-app/open-seo",
        "source_url": "https://github.com/every-app/open-seo",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Competitive-analysis methodology distilled from the OpenSEO skill set; no upstream code or prompts copied.",
    },
    {
        "id": "security-reconnaissance",
        "name": "Security Reconnaissance",
        "description": "Scope a target and map its attack surface before testing.",
        "category": "security",
        "steps": (
            "Confirm scope and authorization; document trust boundaries before testing.",
            "Enumerate the surface: components, entry points, inputs, and third-party integrations.",
            "Map attacker-controlled inputs to the code paths that consume them.",
            "Prioritize the surface by reachability and sensitivity; skip out-of-scope areas.",
            "Deliver a scoped recon report: surface inventory, trust boundaries, and priorities.",
        ),
        "capabilities": ("security", "reconnaissance", "attack surface"),
        "tags": ("security", "recon", "attack surface"),
        "version": "1.0.0",
        "source": "usestrix/strix",
        "source_url": "https://github.com/usestrix/strix",
        "license": "Apache-2.0",
        "origin": "adapted",
        "adaptation_note": "Scoping and attack-surface mapping distilled from the Strix pentesting model; no code copied.",
    },
    {
        "id": "security-validation",
        "name": "Security Finding Validation",
        "description": "Prove a vulnerability is real with a minimal PoC before calling it one.",
        "category": "security",
        "steps": (
            "Find the issue, then reproduce it with a minimal proof-of-concept and concrete steps — evidence, not assertion.",
            "Classify severity by realistic exploitability (reachable, attacker-controlled input), not theoretical worst case.",
            "Record each finding with severity, affected component, reproduction, and root cause.",
            "Flag anything you could not reproduce as unverified rather than downgrading it silently.",
            "Deliver a findings report with validation status and a re-test checklist.",
        ),
        "capabilities": ("security", "validation", "penetration testing"),
        "prompt_profile": "security-pentest-validator",
        "tags": ("security", "pentest", "validation"),
        "version": "1.0.0",
        "source": "usestrix/strix",
        "source_url": "https://github.com/usestrix/strix",
        "license": "Apache-2.0",
        "origin": "adapted",
        "adaptation_note": "Find→validate(PoC)→classify loop distilled from the Strix pentesting model; no code copied.",
    },
    {
        "id": "fix-verify-loop",
        "name": "Fix → Verify Loop",
        "description": "Apply the smallest safe fix, then re-test to prove the finding is closed.",
        "category": "security",
        "steps": (
            "Propose the smallest safe fix that closes the finding without widening scope.",
            "Apply the fix and re-run the proof-of-concept to confirm it no longer triggers.",
            "Re-scan for regressions introduced by the fix.",
            "Record the verification result: closed, partially closed, or still open.",
            "Repeat the loop a bounded number of times; report unresolved findings honestly.",
        ),
        "capabilities": ("remediation", "verification", "security"),
        "prompt_profile": "security-pentest-validator",
        "tags": ("security", "remediation", "re-scan", "verification"),
        "version": "1.0.0",
        "source": "usestrix/strix",
        "source_url": "https://github.com/usestrix/strix",
        "license": "Apache-2.0",
        "origin": "adapted",
        "adaptation_note": "Fix→re-scan→verify loop distilled from the Strix remediation model; no code copied.",
    },
    {
        "id": "repository-analysis",
        "name": "Repository Analysis",
        "description": "Inspect a codebase read-only before changing it: conventions, structure, and impact.",
        "category": "engineering",
        "steps": (
            "Identify the project's technologies, manifests, and build/test entry points.",
            "Read the relevant code and its tests before changing anything.",
            "Match the project's conventions, idioms, and dependency choices rather than importing your own.",
            "Map the blast radius: which modules, callers, and data shapes the change affects.",
            "Record assumptions and anything that could not be verified.",
        ),
        "capabilities": ("codebase analysis", "impact analysis", "conventions"),
        "tags": ("engineering", "analysis", "read-only"),
        "version": "1.0.0",
    },
    {
        "id": "workflow-planning",
        "name": "Workflow Planning",
        "description": "Decompose a goal into a graph of agent steps with clear handoffs.",
        "category": "orchestration",
        "steps": (
            "Decompose the goal into single-purpose steps; each names one role and one deliverable.",
            "Choose the coordination pattern deliberately: sequential, parallel, supervisor, router, or reflection.",
            "Define handoff contracts: what each step receives and must produce for the next.",
            "Add a bounded reflection/review loop instead of unbounded retries.",
            "Keep memory and context explicit; prefer the smallest graph that meets the goal.",
        ),
        "capabilities": ("planning", "multi-agent orchestration", "decomposition"),
        "prompt_profile": "agent-workflow-planner",
        "tags": ("agents", "planning", "orchestration"),
        "version": "1.0.0",
        "source": "NirDiamant/GenAI_Agents",
        "source_url": "https://github.com/NirDiamant/GenAI_Agents",
        "license": "custom (non-commercial)",
        "origin": "adapted",
        "adaptation_note": "Concepts only (planning/routing/reflection patterns) — independently written; no code or prompt text copied (non-commercial license).",
    },
    {
        "id": "knowledge-extraction",
        "name": "Knowledge Extraction",
        "description": "Distill documents into structured, on-demand reference (frameworks, glossary, patterns) instead of dumping source text.",
        "category": "knowledge",
        "steps": (
            "Confirm the source set and scope (files, folders, or globs) before extracting anything.",
            "Extract structure first: a chapter/section index, key terms, and decision rules — not a prose summary.",
            "Separate frameworks, patterns, and anti-patterns into their own reference sections.",
            "Preserve provenance for every extracted rule: source, license, and where it came from.",
            "Keep each reference unit small and loadable on demand so answers stay proportional to the question.",
        ),
        "capabilities": ("knowledge extraction", "documentation", "skill authoring", "distillation"),
        "tags": ("knowledge", "documentation", "skills", "extraction"),
        "version": "1.0.0",
        "source": "virgiliojr94/book-to-skill",
        "source_url": "https://github.com/virgiliojr94/book-to-skill",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Document→structured-skill extraction distilled from book-to-skill; no code or prompt text copied.",
    },
)


# Build the validated registry once the built-in data is defined above.
_BUILT = _build()
BUILTIN_SKILLS = _BUILT
_SKILLS = {s.id: s for s in _BUILT}


__all__ = [
    "BUILTIN_SKILLS",
    "SKILL_CATEGORIES",
    "Skill",
    "SkillError",
    "SkillLibraryError",
    "get_skill",
    "list_skills",
    "list_skills_by_category",
    "render_skill_context",
    "resolve_skill_prompt",
    "suggest_skills_for_task",
    "validate_skill",
]

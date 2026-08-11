"""Lightweight intent classifier for user inputs.

Categories of non-task input that the Master agent handles locally
without spawning the full multi-agent pipeline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_GREETINGS = {
    "hello", "hi", "hey", "yo", "hola", "greetings", "good morning",
    "good afternoon", "good evening", "sup", "howdy",
}
_CASUAL = {
    "thanks", "thank you", "thx", "ty", "ok", "okay", "cool", "nice",
    "great", "awesome", "sure", "yep", "yes", "no", "nope", "bye",
    "goodbye", "see ya", "later", "cya",
}
_QUESTIONS = {
    "what can you do", "what do you do", "how does this work",
    "who are you", "what are you", "help", "commands",
    "capabilities", "features",
}

INTENT_TASK = "task"
INTENT_GREETING = "greeting"
INTENT_CASUAL = "casual"
INTENT_QUESTION = "question"


def classify_intent(text: str) -> str:
    """Classify user input so non-task messages are handled locally.

    Returns one of ``INTENT_TASK``, ``INTENT_GREETING``, ``INTENT_CASUAL``,
    or ``INTENT_QUESTION``.
    """
    cleaned = text.strip().lower().rstrip(".!?")
    if not cleaned or len(cleaned) < 2:
        return INTENT_CASUAL
    if cleaned in _GREETINGS:
        return INTENT_GREETING
    if cleaned in _CASUAL:
        return INTENT_CASUAL
    for phrase in _QUESTIONS:
        if phrase in cleaned:
            return INTENT_QUESTION
    if len(cleaned.split()) == 1 and len(cleaned) <= 8:
        return INTENT_CASUAL
    return INTENT_TASK


def _format_proposals() -> str:
    """Render detected optimization proposals as console text."""
    _SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)

    try:
        from self_evolve import detect_optimization_loops
        proposals = detect_optimization_loops()
        if not proposals:
            return "no optimization-loop proposals detected"
        lines = []
        for p in proposals:
            lines.append(f"  [{p.id}] x{p.count} — {p.suggestion}")
        return "\n".join(lines)
    except ImportError:
        return "self_evolve module not available"

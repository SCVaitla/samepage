"""Prompt-injection guard: docs are data, never instructions.

A line that reads like an instruction aimed at an AI is reported on the card and
left out of every fact the engine extracts. Patterns are generic; none of them
names a product fact.
"""

from __future__ import annotations

import re

PATTERNS = [
    # "ignore/disregard ... other/previous ... sources/instructions"
    re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(other|previous|prior|above|all|any)\b"
        r".{0,25}\b(sources?|instructions?|rules|context|documents?)\b",
        re.IGNORECASE,
    ),
    # "AI agents: ...", "Assistant, ...", "LLMs: ..." addressed at the reader
    re.compile(
        r"(^|[.!?]\s+)(note for\s+)?(ai|llm|assistant|chatbot|language model)s?(\s+agents?)?\s*[:,]",
        re.IGNORECASE,
    ),
    # "you must say/answer/respond/tell"
    re.compile(r"\byou (must|should|are instructed to) (always )?(say|answer|respond|reply|tell)\b", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
]


def looks_like_injection(line: str) -> bool:
    return any(p.search(line) for p in PATTERNS)

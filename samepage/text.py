"""Small text helpers: tokenizing and the company glossary.

The glossary (corpus/glossary.yaml) maps phrases that mean the same thing to one
token, so "single sign-on", "SSO" and "SAML" all become "g:sso". It is data that
the docs owners maintain, not code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "get",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "to",
        "up",
        "us",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yes",
        "no",
        "not",
    ]
)
WORD = re.compile(r"[a-z0-9]+(?:[/'-][a-z0-9]+)*")


def stem(word: str) -> str:
    """Very small stemmer: enough to match 'limited'/'limit' and 'plans'/'plan'."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


class Glossary:
    def __init__(self, groups: dict[str, list[str]]) -> None:
        pairs = [(phrase.lower(), name) for name, phrases in groups.items() for phrase in phrases]
        pairs.sort(key=lambda p: len(p[0]), reverse=True)  # longest phrase first
        self._pairs = pairs
        self._patterns = [
            (re.compile(r"(?<![a-z0-9:])" + re.escape(phrase) + r"(?![a-z0-9])"), f" g:{name} ")
            for phrase, name in pairs
        ]

    @classmethod
    def load(cls, path: Path) -> Glossary:
        if not path.exists():
            return cls({})
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls({str(k): [str(p) for p in v] for k, v in (data.get("groups") or {}).items()})

    def tokens(self, text: str) -> list[str]:
        """Lowercase, replace glossary phrases with group tokens, drop stopwords, stem."""
        # Hyphens and underscores join words ("requests-per-minute", "seat_limit"); treat them as spaces,
        # except inside numbers and value shorthands like "24/7" (slashes are kept).
        lowered = " " + re.sub(r"(?<=[a-z])[-_](?=[a-z])", " ", text.lower().replace("_", " ")) + " "
        for pattern, replacement in self._patterns:
            lowered = pattern.sub(replacement, lowered)
        out: list[str] = []
        for raw in lowered.split():
            if raw.startswith("g:"):
                out.append(raw)
                continue
            for word in WORD.findall(raw):
                if word not in STOPWORDS:
                    out.append(stem(word))
        return out

    def token_set(self, parts: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for part in parts:
            result.update(self.tokens(part))
        return result


def collapse_ws(text: str) -> str:
    return " ".join(text.split())

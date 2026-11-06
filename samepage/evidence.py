"""Evidence verification: every quote must exist verbatim in the cited file, at the cited lines.

"Verbatim" here means the exact characters, except that runs of whitespace (including
line breaks) count as one space, because markdown wraps lines without changing meaning.
An agent may be off by a few lines (`slack`); the verifier then reports the span where
the quote actually is. A quote that cites an injected instruction is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass

from samepage.corpus import Corpus
from samepage.injection import looks_like_injection
from samepage.models import ContractClaim
from samepage.text import collapse_ws

MIN_QUOTE_CHARS = 8


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    reason: str
    path: str = ""
    line_start: int = 0
    line_end: int = 0


def find_span(lines: list[str], quote: str, first: int, last: int) -> tuple[int, int] | None:
    """Tightest [start, end] (1-based, inside first..last) whose text contains the quote.

    Scans ends in order and, for each end, grows the span backwards, so the first hit
    is the earliest-ending, shortest span.
    """
    target = collapse_ws(quote)
    first, last = max(1, first), min(len(lines), last)
    if not target or first > last:
        return None
    for end in range(first, last + 1):
        for start in range(end, first - 1, -1):
            if target in collapse_ws(" ".join(lines[start - 1 : end])):
                return start, end
    return None


def verify_quote(corpus: Corpus, claim: ContractClaim, slack: int = 2) -> QuoteCheck:
    path = corpus.normalize_path(claim.source_path)
    if path is None:
        return QuoteCheck(False, f"cited file {claim.source_path!r} is not in the corpus")
    if len(collapse_ws(claim.quote)) < MIN_QUOTE_CHARS:
        return QuoteCheck(False, "quote too short to count as evidence")
    if claim.line_end < claim.line_start:
        return QuoteCheck(False, "line_end is before line_start")
    lines = corpus.files[path]
    span = find_span(lines, claim.quote, claim.line_start - slack, claim.line_end + slack)
    if span is None:
        return QuoteCheck(False, f"quote not found in {path} near lines {claim.line_start}-{claim.line_end}")
    if any(looks_like_injection(lines[n - 1]) for n in range(span[0], span[1] + 1)):
        return QuoteCheck(False, "quote cites a line that reads like an instruction to AI agents")
    return QuoteCheck(True, "", path, span[0], span[1])

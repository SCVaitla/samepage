"""Test helpers.

The agent answers built here are HAND-WRITTEN test inputs in the Answer Contract shape,
not recorded agent output. Line numbers are looked up from the corpus by searching for
the quote, so tests never hardcode where a fact sits in a file.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from samepage.corpus import Corpus
from samepage.models import AgentAnswer, AnswerContract, ContractClaim

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"


@cache
def corpus() -> Corpus:
    return Corpus.from_dir(CORPUS_DIR)


def span_of(path: str, quote: str, c: Corpus | None = None) -> tuple[int, int]:
    from samepage.evidence import find_span

    lines = (c or corpus()).files[path]
    span = find_span(lines, quote, 1, len(lines))
    assert span is not None, f"test quote not in {path}: {quote!r}"
    return span


def claim(
    path: str,
    quote: str,
    value: str,
    entity: str = "x",
    attribute: str = "y",
    qualifier: str = "",
    c: Corpus | None = None,
) -> ContractClaim:
    start, end = span_of(path, quote, c)
    return ContractClaim(
        entity=entity,
        attribute=attribute,
        qualifier=qualifier,
        value=value,
        source_path=f"corpus/{path}",
        line_start=start,
        line_end=end,
        quote=quote,
    )


def answer(agent: str, *claims: ContractClaim, text: str = "", unknown: bool = False) -> AgentAnswer:
    contract = AnswerContract(
        answer=text or "answer", claims=list(claims), unknown=unknown, confidence="high" if claims else "low"
    )
    raw = "```json\n" + contract.model_dump_json() + "\n```"
    return AgentAnswer(agent=agent, raw=raw, contract=contract)


def unknown(agent: str) -> AgentAnswer:
    return answer(agent, unknown=True, text="The docs do not say.")


def failed(agent: str, error: str) -> AgentAnswer:
    return AgentAnswer(agent=agent, raw="", contract=None, error=error)


def raw_json(contract: AnswerContract) -> str:
    return json.dumps(contract.model_dump())

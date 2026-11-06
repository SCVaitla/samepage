"""Pydantic schemas shared by every module.

The Answer Contract is what each worker agent must return. Everything else is
produced by the engine. Agent output is untrusted input: these models validate
shape and size, and nothing in them is ever executed or followed as an instruction.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Outcome(StrEnum):
    VERIFIED = "VERIFIED"
    COMPATIBLE = "COMPATIBLE"
    CONFLICT = "CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    RESOLVED = "RESOLVED"

    @property
    def is_alarm(self) -> bool:
        return self in (Outcome.CONFLICT, Outcome.SOURCE_CONFLICT)


# ---- Answer Contract (what agents send) ---------------------------------------


class ContractClaim(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    entity: str = Field(max_length=200)
    attribute: str = Field(max_length=200)
    qualifier: str = Field(default="", max_length=200)
    value: str = Field(max_length=500)
    source_path: str = Field(max_length=300)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    quote: str = Field(max_length=2000)


class AnswerContract(BaseModel):
    """One worker agent's answer. claims[0] must directly answer the question (the headline claim)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question_id: str = Field(default="", max_length=100)
    answer: str = Field(default="", max_length=4000)
    claims: list[ContractClaim] = Field(default_factory=list, max_length=20)
    sources_consulted: list[str] = Field(default_factory=list, max_length=50)
    confidence: str = Field(default="low", max_length=10)
    unknown: bool = False


class AgentAnswer(BaseModel):
    """An answer as received: the raw text, plus the parsed contract if parsing worked."""

    agent: str
    raw: str
    contract: AnswerContract | None = None
    error: str | None = None  # "timeout", "invalid_json: ...", ...
    sealed_at: str = ""
    sha256: str = ""


# ---- Engine output ---------------------------------------------------------------


class Passage(BaseModel):
    """A block of a source file with its stable line span."""

    path: str
    source_id: str
    authority: int
    line_start: int
    line_end: int
    heading: str
    text: str


class Evidence(BaseModel):
    """A value for the fact, found in one place (an agent's claim or a corpus passage)."""

    path: str
    source_id: str
    authority: int
    owner: str
    surface: str
    line_start: int
    line_end: int
    quote: str
    value_text: str  # the words the source used
    value_key: str  # the normalized value, e.g. "days:14"
    found_by: str  # an agent name, or "engine-scan"


class CheckedClaim(BaseModel):
    agent: str
    claim: ContractClaim
    verified: bool
    reason: str = ""
    value_key: str = ""
    value_confirmed: bool = False  # the quote itself states this value (only for value kinds we can read)


class Proposal(BaseModel):
    value_key: str
    value_text: str
    because: str
    winning: list[Evidence]
    losing: list[Evidence]


class Injection(BaseModel):
    path: str
    line: int
    text: str


class CaseResult(BaseModel):
    question: str
    outcome: Outcome
    reasons: list[str]
    checked: list[CheckedClaim]
    evidence: list[Evidence]  # everything known about the fact, grouped by value later
    proposal: Proposal | None = None
    injections: list[Injection] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)  # agent -> plain-language answer

    def evidence_validity(self) -> tuple[int, int]:
        """(verified claims, all claims) across both agents."""
        return sum(c.verified for c in self.checked), len(self.checked)

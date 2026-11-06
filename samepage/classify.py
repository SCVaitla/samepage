"""Compare two sealed answers, scan the corpus for the same fact, and pick an outcome state.

Order of checks (first match wins):
  1. An answer failed (timeout, invalid JSON)                      -> UNSUPPORTED
  2. Both agents say the docs don't answer it                      -> UNSUPPORTED
  3. An agent's headline claim did not verify (quote not at the cited
     lines, passage not about the question, or the quote does not state
     the claimed value)                                              -> UNSUPPORTED
  4. One agent found an answer, the other found none               -> CONFLICT
  5. Headline values differ after normalization                    -> CONFLICT
  6. Agents agree, but another passage gives a different value     -> SOURCE_CONFLICT
  6b. Agents agree, but the value can't be read from the quotes or
      cross-checked against the docs (free text, no plan to scan for) -> UNSUPPORTED
  7. Agents agree; the evidence words the value in different ways  -> COMPATIBLE
  8. Agents agree; every piece of evidence words it the same way   -> VERIFIED

Comparison is plain code. Nothing here calls a model, so the same input always gives
the same output. Authority levels feed the *proposal* shown to the human; they never
decide the outcome on their own.
"""

from __future__ import annotations

from dataclasses import dataclass

from samepage.corpus import Corpus
from samepage.evidence import verify_quote
from samepage.models import (
    AgentAnswer,
    CaseResult,
    CheckedClaim,
    ContractClaim,
    Evidence,
    Outcome,
    Proposal,
)
from samepage.text import collapse_ws
from samepage.values import Value, extract_for, normalize_claim_value

GENERIC_TOKENS = frozenset(
    {
        "g:plan",
        "g:workspace",
        "juniper",
        "desk",
        "feature",
        "available",
        "availability",
        "policy",
        "option",
        "detail",
        "info",
        "product",
        "include",
        "offer",
        "allow",
        "able",
        "use",
        "turn",
        "get",
        "customer",
        "team",
    }
)
# Words about the *size* of a value, not the fact: "how many days", "how long". Never anchors.
_SIZE = ("day", "week", "month", "year", "hour", "minute", "second", "time")
UNIT_WORDS = frozenset({*_SIZE, *(w + "s" for w in _SIZE), "long", "many", "much", "number", "most", "max", "maximum"})
SCANNABLE_KINDS = frozenset({"days", "seats", "per_min", "schedule", "bool"})


@dataclass(frozen=True)
class Fact:
    """What the engine looks for in the corpus: a kind of value, for a plan, near some anchor words."""

    kind: str
    plan: str | None
    anchors: frozenset[str]


class Engine:
    def __init__(self, corpus: Corpus, slack: int = 2, min_anchor_terms: int = 1) -> None:
        self.corpus = corpus
        self.slack = slack
        self.min_anchor_terms = min_anchor_terms

    # ---- helpers -------------------------------------------------------------

    def plan_named(self, *texts: str) -> str | None:
        tokens = self.corpus.glossary.token_set(texts)
        for plan in self.corpus.plans:
            if plan in tokens:
                return plan
        return None

    def anchors(self, *texts: str) -> frozenset[str]:
        """Topic words: glossary tokens minus generic words, plan names and size words."""
        drop = GENERIC_TOKENS | UNIT_WORDS | set(self.corpus.plans)
        return frozenset(self.corpus.glossary.token_set(texts) - drop)

    def fact_for(self, claims: list[ContractClaim], question: str, kind: str) -> Fact:
        """The fact to scan for. Anchor words come from the question AND every agent's claim,
        so no single agent's choice of names decides which docs get checked."""
        parts = [question, *(c.entity for c in claims), *(c.attribute for c in claims)]
        plan = self.plan_named(question) or next(
            (p for c in claims if (p := self.plan_named(c.entity, c.attribute, c.qualifier))), None
        )
        return Fact(kind=kind, plan=plan, anchors=self.anchors(*parts))

    def value_of(self, claim: ContractClaim, question: str) -> Value:
        plan = self.plan_named(claim.entity, claim.attribute, claim.qualifier) or self.plan_named(question)
        return normalize_claim_value(claim.value, claim.quote, claim.attribute, plan, self.corpus.plans)

    def evidence_from(
        self, path: str, line_start: int, line_end: int, quote: str, value: Value, found_by: str
    ) -> Evidence:
        fam = self.corpus.family_of(path)
        if fam is None:
            raise ValueError(f"{path} is not a declared source")
        return Evidence(
            path=path,
            source_id=fam.id,
            authority=fam.authority,
            owner=fam.owner,
            surface=fam.surface,
            line_start=line_start,
            line_end=line_end,
            quote=quote,
            value_text=value.text,
            value_key=value.key,
            found_by=found_by,
        )

    # ---- corpus scan ---------------------------------------------------------

    def scan(self, fact: Fact) -> list[Evidence]:
        """Every passage in the corpus that states a value of this kind for this fact."""
        if fact.kind not in SCANNABLE_KINDS or not fact.anchors:
            return []
        if fact.kind == "bool" and fact.plan is None:
            return []
        found: list[Evidence] = []
        for passage in self.corpus.passages:
            tokens = self.corpus.glossary.token_set([passage.heading, passage.text])
            if len(fact.anchors & tokens) < min(self.min_anchor_terms, len(fact.anchors)):
                continue
            if fact.plan and not self._plan_guard(fact, tokens, passage.text):
                continue
            value = extract_for(fact.kind, passage.text, fact.plan, self.corpus.plans)
            if value is None:
                continue
            lines = self.corpus.files[passage.path][passage.line_start - 1 : passage.line_end]
            found.append(
                self.evidence_from(
                    passage.path,
                    passage.line_start,
                    passage.line_end,
                    collapse_ws(" ".join(lines)),
                    value,
                    "engine-scan",
                )
            )
        return found

    def _plan_guard(self, fact: Fact, tokens: set[str], text: str) -> bool:
        """A number fact for a plan must name that plan (or 'all plans'). A yes/no
        availability fact may name any plan: 'Enterprise only' answers 'on Starter?' too."""
        if _mentions_all_plans(text):
            return True
        if fact.kind == "bool":
            return any(p in tokens for p in self.corpus.plans)
        return fact.plan in tokens

    # ---- the decision ----------------------------------------------------------

    def check(self, answer: AgentAnswer, question: str) -> list[CheckedClaim]:
        """Verify each claim: the quote exists at the cited lines, the quoted passage is about
        the question, and the quote itself states the claimed value."""
        if answer.contract is None or answer.contract.unknown:
            return []
        topic = self.anchors(question)
        checked = []
        for claim in answer.contract.claims:
            result = verify_quote(self.corpus, claim, self.slack)
            value = self.value_of(claim, question)
            ok, reason, confirmed = result.ok, result.reason, False
            if ok and topic and not (topic & self._context_tokens(result.path, result.line_start, result.line_end)):
                ok, reason = False, "the quoted passage is not about the question"
            plan = self.plan_named(claim.entity, claim.attribute, claim.qualifier) or self.plan_named(question)
            readable = value.kind in SCANNABLE_KINDS and not (value.kind == "bool" and plan is None)
            if ok and readable:
                stated = extract_for(value.kind, claim.quote, plan, self.corpus.plans)
                if stated is None or stated.key != value.key:
                    said = stated.key if stated else "no such value"
                    ok, reason = False, f"the quote does not state the claimed value ({value.key}; quote: {said})"
                else:
                    confirmed = True
            checked.append(
                CheckedClaim(
                    agent=answer.agent,
                    claim=claim,
                    verified=ok,
                    reason=reason,
                    value_key=value.key,
                    value_confirmed=confirmed,
                )
            )
        return checked

    def _context_tokens(self, path: str, start: int, end: int) -> set[str]:
        """Words of the passages around a verified quote (including their headings)."""
        parts = [
            p.heading + " " + p.text
            for p in self.corpus.passages
            if p.path == path and p.line_start <= end and start <= p.line_end
        ]
        parts.append(" ".join(self.corpus.files[path][start - 1 : end]))
        return self.corpus.glossary.token_set(parts)

    def evaluate(self, question: str, answers: list[AgentAnswer]) -> CaseResult:
        answers = sorted(answers, key=lambda a: a.agent)  # order-independent by construction
        reasons: list[str] = []
        checked = [c for a in answers for c in self.check(a, question)]
        plain = {a.agent: a.contract.answer for a in answers if a.contract is not None}

        def done(outcome: Outcome, why: list[str], evidence: list[Evidence]) -> CaseResult:
            proposal = propose(evidence) if outcome.is_alarm else None
            return CaseResult(
                question=question,
                outcome=outcome,
                reasons=why,
                checked=checked,
                evidence=evidence,
                proposal=proposal,
                answers=plain,
                injections=list(self.corpus.injections),
            )

        if len(answers) < 2:
            return done(Outcome.UNSUPPORTED, ["SamePage needs two independent answers to compare."], [])

        failed = [a for a in answers if a.contract is None]
        if failed:
            reasons += [f"{a.agent} gave no usable answer ({a.error or 'unparseable'})" for a in failed]
            return done(Outcome.UNSUPPORTED, reasons, [])

        unknown = [a for a in answers if a.contract is not None and (a.contract.unknown or not a.contract.claims)]
        known = [a for a in answers if a not in unknown]
        if not known:
            return done(
                Outcome.UNSUPPORTED,
                ["Neither agent found this in the docs. Treat any answer as unverified."],
                [],
            )

        headlines: dict[str, CheckedClaim] = {}
        for a in known:
            head = next(c for c in checked if c.agent == a.agent)  # claims[0] is the headline claim
            if not head.verified:
                return done(
                    Outcome.UNSUPPORTED,
                    [f"{a.agent}'s headline claim could not be verified: {head.reason}"],
                    [],
                )
            headlines[a.agent] = head

        agent_evidence = [self._headline_evidence(h, question) for h in headlines.values()]
        kinds = {h.value_key.split(":", 1)[0] for h in headlines.values()}
        fact = self.fact_for(
            [h.claim for h in headlines.values()], question, kinds.pop() if len(kinds) == 1 else "mixed"
        )
        scanned = _dedupe(self.scan(fact), agent_evidence)
        evidence = agent_evidence + scanned

        if unknown:
            reasons.append(f"{unknown[0].agent} found no answer in the docs, but {known[0].agent} did.")
            return done(Outcome.CONFLICT, reasons, evidence)

        values = {h.value_key for h in headlines.values()}
        if len(values) > 1:
            parts = [f"{agent} says {h.claim.value!r} ({h.value_key})" for agent, h in headlines.items()]
            reasons.append("The agents disagree: " + "; ".join(parts) + ".")
            return done(Outcome.CONFLICT, reasons, evidence)

        agreed = values.pop()
        contradicting = [e for e in scanned if e.value_key != agreed]
        if contradicting:
            where = ", ".join(f"{e.path}:{e.line_start}" for e in contradicting)
            reasons.append(f"Both agents agree on {agreed}, but other docs say otherwise ({where}).")
            return done(Outcome.SOURCE_CONFLICT, reasons, evidence)

        # Agreement only counts when SamePage could check the value against the quote AND
        # cross-check the rest of the docs. Otherwise it is not presented as fact.
        unchecked = (
            fact.kind not in SCANNABLE_KINDS
            or (fact.kind == "bool" and fact.plan is None)
            or not fact.anchors
            or not all(h.value_confirmed for h in headlines.values())
        )
        if unchecked:
            reasons.append(
                "The agents agree, but SamePage cannot check this kind of answer against the docs "
                "(the value is free text, or no plan or topic to scan for). Treat it as unverified."
            )
            return done(Outcome.UNSUPPORTED, reasons, evidence)
        # Yes/no facts have no wording to compare; for the rest, compare how each source wrote the value.
        wordings = {_wording(e.value_text) for e in evidence} if fact.kind != "bool" else set()
        if len(wordings) > 1:
            reasons.append(
                "The agents agree; the docs word it differently ("
                + ", ".join(sorted(wordings))
                + ") but mean the same."
            )
            return done(Outcome.COMPATIBLE, reasons, evidence)
        reasons.append("The agents agree, the quotes are verified, and no other doc contradicts them.")
        return done(Outcome.VERIFIED, reasons, evidence)

    def _headline_evidence(self, head: CheckedClaim, question: str) -> Evidence:
        result = verify_quote(self.corpus, head.claim, self.slack)
        value = self.value_of(head.claim, question)
        # Prefer the words the *source* used ("1k rpm") over the agent's rewording ("1000"),
        # so the wording check below compares the docs, not the agents' style.
        plan = self.plan_named(head.claim.entity, head.claim.attribute, head.claim.qualifier) or self.plan_named(
            question
        )
        in_quote = extract_for(value.kind, head.claim.quote, plan, self.corpus.plans)
        if in_quote is not None and in_quote.key == value.key and value.kind != "bool":
            value = in_quote
        return self.evidence_from(
            result.path, result.line_start, result.line_end, collapse_ws(head.claim.quote), value, head.agent
        )


def propose(evidence: list[Evidence]) -> Proposal | None:
    """Suggest a truth for the human: the value backed by the highest-authority source
    (lowest number), then by the most sources. Advice only; the human rules."""
    if not evidence:
        return None
    groups: dict[str, list[Evidence]] = {}
    for e in evidence:
        groups.setdefault(e.value_key, []).append(e)
    best_key = min(groups, key=lambda k: (min(e.authority for e in groups[k]), -_distinct(groups[k]), k))
    winning = groups[best_key]
    top = min(winning, key=lambda e: e.authority)
    losing = [e for k, g in groups.items() if k != best_key for e in g]
    because = (
        f"{top.path} (authority {top.authority}, highest of the sources involved) says "
        f"{top.value_text!r}; {_distinct(winning)} source file(s) agree."
    )
    return Proposal(value_key=best_key, value_text=top.value_text, because=because, winning=winning, losing=losing)


def _distinct(group: list[Evidence]) -> int:
    return len({e.path for e in group})


def _wording(text: str) -> str:
    return collapse_ws(text.lower()).removeprefix("up to ").strip(" .")


def _mentions_all_plans(text: str) -> bool:
    from samepage.values import UNIVERSAL_PLANS

    return UNIVERSAL_PLANS.search(text) is not None


def _dedupe(scanned: list[Evidence], agent_evidence: list[Evidence]) -> list[Evidence]:
    """Drop scan hits that are the same passage and value an agent already cited."""
    out = []
    for e in scanned:
        duplicate = any(
            a.path == e.path
            and a.value_key == e.value_key
            and a.line_start <= e.line_end
            and e.line_start <= a.line_end
            for a in agent_evidence
        )
        if not duplicate:
            out.append(e)
    return out

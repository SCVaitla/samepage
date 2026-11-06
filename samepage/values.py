"""Value normalization: turn the words a source or agent used into a comparable key.

Examples:  "14 days", "two weeks", "14-day"            -> "days:14"
           "1,000 requests per minute", "1k rpm"       -> "per_min:1000"
           "up to 10 seats", "10 members"              -> "seats:10"
           "24/7", "round-the-clock"                   -> "schedule:24x7"
           "Enterprise only" (asked about Starter)     -> "bool:false"
           "yes", "available", "true"                  -> "bool:true"

Keys are deterministic and the rules are generic (units, number words, plan lists);
none of them knows which facts are planted in the demo corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "sixty": 60,
    "ninety": 90,
}
NUM = r"(?<![$\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?(?![\w])"
NUM_OR_WORD = r"(?<![$\w.,])(\d{1,3}(?:,\d{3})+|\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"

DAYS = re.compile(NUM_OR_WORD + r"[\s-]+(day|days|week|weeks|month|months|year|years)\b", re.IGNORECASE)
SEATS = re.compile(NUM_OR_WORD + r"\s+(seats?|members?|users?|people|teammates)\b", re.IGNORECASE)
RATE = re.compile(
    NUM + r"\s*(requests?\s*(?:per|/|a)\s*(minute|min|hour|second|sec)|req/min|rpm|rph|rps)\b",
    re.IGNORECASE,
)
SCHEDULE_247 = re.compile(
    r"24\s*/\s*7|24x7|24-7|round[- ]the[- ]clock|around[- ]the[- ]clock|24 hours a day,? (7|seven) days a week",
    re.IGNORECASE,
)
UNIVERSAL_PLANS = re.compile(r"\b(all|every|any|each|whatever)\s+(of our\s+)?plans?\b", re.IGNORECASE)
NEGATION = re.compile(r"\b(not|no|isn't|aren't|unavailable|excluding|except|without|never)\b", re.IGNORECASE)
ONLY = re.compile(r"\b(only|exclusive(ly)?|just)\b", re.IGNORECASE)
TRUE_WORDS = {"true", "yes", "available", "included", "supported", "enabled", "allowed", "y"}
FALSE_WORDS = {
    "false",
    "no",
    "not available",
    "unavailable",
    "not included",
    "not supported",
    "unsupported",
    "none",
    "disabled",
    "n",
}
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


@dataclass(frozen=True)
class Value:
    key: str  # e.g. "days:14"
    text: str  # the words that produced it
    pos: int  # character offset in the searched text (for "nearest to the plan" choices)

    @property
    def kind(self) -> str:
        return self.key.split(":", 1)[0]


def _number(raw: str, k: str | None = None) -> float:
    raw = raw.lower()
    value = float(NUMBER_WORDS[raw]) if raw in NUMBER_WORDS else float(raw.replace(",", ""))
    return value * 1000 if k else value


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def find_days(text: str) -> list[Value]:
    out = []
    for m in DAYS.finditer(text):
        unit = m.group(2).lower().rstrip("s")
        out.append(Value(f"days:{_fmt(_number(m.group(1)) * UNIT_DAYS[unit])}", m.group(0), m.start()))
    return out


def find_seats(text: str) -> list[Value]:
    return [Value(f"seats:{_fmt(_number(m.group(1)))}", m.group(0), m.start()) for m in SEATS.finditer(text)]


def find_rates(text: str) -> list[Value]:
    out = []
    for m in RATE.finditer(text):
        n = _number(m.group(1), m.group(2))
        unit = (m.group(4) or m.group(3)).lower()
        if unit in ("hour", "rph"):
            n = n / 60
        elif unit in ("second", "sec", "rps"):
            n = n * 60
        out.append(Value(f"per_min:{_fmt(n)}", m.group(0), m.start()))
    return out


def find_schedules(text: str) -> list[Value]:
    return [Value("schedule:24x7", m.group(0), m.start()) for m in SCHEDULE_247.finditer(text)]


def plan_availability(text: str, plans: list[str]) -> set[str] | None:
    """Which plans a passage says something is available on, or None if it doesn't say.

    Clause by clause: a plan named after a negation is excluded, "only/exclusive" makes
    the named plans the whole set, and "all/every plan" means every plan.
    """
    if not plans:
        return None
    included: set[str] = set()
    excluded: set[str] = set()
    universal = False
    restrictive = False
    for clause in re.split(r"(?<=[.;!?\n])", text):
        if clause.strip().rstrip("*_ ").endswith("?"):
            continue  # a question asserts nothing ("Can a Starter customer use SSO?")
        lowered = clause.lower()
        if UNIVERSAL_PLANS.search(clause) and not NEGATION.search(clause):
            universal = True
        for plan in plans:
            for m in re.finditer(r"\b" + re.escape(plan) + r"\b", lowered):
                before = lowered[max(0, m.start() - 60) : m.start()]
                if NEGATION.search(before):
                    excluded.add(plan)
                else:
                    included.add(plan)
                    if ONLY.search(lowered[max(0, m.start() - 20) : m.end() + 20]):
                        restrictive = True
    if universal and not excluded:
        return set(plans)
    if restrictive and included:
        return included - excluded
    if excluded and not included:
        return set(plans) - excluded
    if included or excluded:
        return included - excluded if included else set(plans) - excluded
    return None


def find_by_kind(kind: str, text: str) -> list[Value]:
    finders = {"days": find_days, "seats": find_seats, "per_min": find_rates, "schedule": find_schedules}
    finder = finders.get(kind)
    return finder(text) if finder else []


def bool_key(value: str) -> str | None:
    v = " ".join(value.lower().replace("_", " ").split()).strip(".!")
    if v in TRUE_WORDS:
        return "bool:true"
    if v in FALSE_WORDS:
        return "bool:false"
    return None


def text_key(value: str) -> str:
    return "text:" + "_".join(re.findall(r"[a-z0-9]+", value.lower()))


def normalize_claim_value(value: str, quote: str, attribute: str, plan: str | None, plans: list[str]) -> Value:
    """Normalize an agent's claim value. The quote and attribute supply a unit for bare numbers."""
    for finder in (find_schedules, find_rates, find_days, find_seats):
        found = finder(value)
        if found:
            return Value(found[0].key, value, 0)
    if bk := bool_key(value):
        return Value(bk, value, 0)
    if plan:
        avail = plan_availability(value, plans)
        if avail is not None:
            return Value(f"bool:{str(plan in avail).lower()}", value, 0)
    bare = re.fullmatch(r"\s*(?:up to\s+)?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?\s*", value, re.IGNORECASE)
    if bare:
        number = _number(bare.group(1), bare.group(2))
        # Same number with a unit in the quote, or a unit word in the attribute name.
        for finder in (find_rates, find_days, find_seats):
            for v in finder(quote):
                if v.key.endswith(":" + _fmt(number)):
                    return Value(v.key, value, 0)
        hints = {
            "seat": "seats",
            "member": "seats",
            "user": "seats",
            "day": "days",
            "window": "days",
            "minute": "per_min",
            "rate": "per_min",
            "rpm": "per_min",
        }
        for hint, kind in hints.items():
            if hint in attribute.lower():
                return Value(f"{kind}:{_fmt(number)}", value, 0)
        return Value(f"number:{_fmt(number)}", value, 0)
    return Value(text_key(value), value, 0)


def extract_for(kind: str, text: str, plan: str | None, plans: list[str]) -> Value | None:
    """Find the value of `kind` in a passage. With a plan, take the value nearest that plan's name."""
    if kind == "bool":
        if plan is None:
            return None
        avail = plan_availability(text, plans)
        if avail is None:
            return None
        return Value(f"bool:{str(plan in avail).lower()}", _availability_words(text), 0)
    found = find_by_kind(kind, text)
    if not found:
        return None
    if plan is None:
        return found[0]
    mentions = [m.start() for m in re.finditer(r"\b" + re.escape(plan) + r"\b", text, re.IGNORECASE)]
    if not mentions:
        return found[0]  # the plan is named in the heading; the block's first value applies

    def distance(v: Value) -> int:
        # Prefer values written after the plan's name ("Pro: 1,000"), then before it.
        return min((v.pos - m) if v.pos >= m else (m - v.pos) * 3 for m in mentions)

    return min(found, key=distance)


def _availability_words(text: str) -> str:
    m = UNIVERSAL_PLANS.search(text)
    if m:
        return m.group(0)
    return text if len(text) <= 120 else text[:117] + "..."

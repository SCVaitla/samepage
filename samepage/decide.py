"""Human rulings: approve the proposal, override with another source, or reject.

Who may rule: anyone in SAMEPAGE_APPROVERS, or an owner of a source on the losing
side (owner routing). Authority levels are advice only; this is where a person decides.
"""

from __future__ import annotations

from dataclasses import dataclass

from samepage.cards import owners_to_notify
from samepage.models import CaseResult, Evidence
from samepage.store import Store

OPEN_FOR_RULING = {"CONFLICT", "SOURCE_CONFLICT"}


@dataclass(frozen=True)
class Edit:
    """One passage the fix must change."""

    path: str
    line_start: int
    line_end: int
    current_quote: str
    current_value: str


@dataclass(frozen=True)
class Ruling:
    ok: bool
    message: str
    truth_value: str | None = None
    truth_quote: str = ""
    truth_path: str = ""
    edits: tuple[Edit, ...] = ()


def can_rule(user: str, result: CaseResult, approvers: set[str]) -> bool:
    who = user.strip().lstrip("@").lower()
    owners = {o.lstrip("@").lower() for o in owners_to_notify(result)}
    return bool(who) and (who in approvers or who in owners)


def _edits(losing: list[Evidence]) -> tuple[Edit, ...]:
    seen: set[tuple[str, int]] = set()
    out = []
    for e in sorted(losing, key=lambda e: (e.path, e.line_start)):
        if (e.path, e.line_start) not in seen:
            seen.add((e.path, e.line_start))
            out.append(Edit(e.path, e.line_start, e.line_end, e.quote, e.value_text))
    return tuple(out)


def rule(store: Store, case_id: str, user: str, verb: str, arg: str, approvers: set[str]) -> Ruling:
    row = store.case(case_id)
    result = store.result(case_id)
    if row is None or result is None:
        return Ruling(False, f"No case `{case_id}`.")
    if row["state"] not in OPEN_FOR_RULING:
        return Ruling(False, f"Case `{case_id}` is {row['state']}; there is nothing to rule on.")
    if not can_rule(user, result, approvers):
        owners = " ".join(owners_to_notify(result)) or "the configured approvers"
        return Ruling(False, f"{user} can't rule on `{case_id}`. Ask {owners}, or add them to SAMEPAGE_APPROVERS.")
    if result.proposal is None:  # alarms always carry a proposal
        return Ruling(False, f"Case `{case_id}` has no proposal to rule on.")

    if verb == "reject":
        reason = arg or "no reason given"
        store.record_decision(case_id, user, "reject", None, [], [], reason)
        store.set_state(case_id, "REJECTED")
        return Ruling(True, f"Recorded: {user} rejected case `{case_id}` ({reason}). No fix will be opened.")

    if verb == "approve":
        winning, losing = result.proposal.winning, result.proposal.losing
        rationale = arg or "accepted the proposed truth"
    elif verb == "override":
        path = arg.split()[0].removeprefix("corpus/") if arg else ""
        chosen = [e for e in result.evidence if e.path == path]
        if not chosen:
            files = ", ".join(sorted({e.path for e in result.evidence}))
            return Ruling(False, f"`{path or '?'}` isn't part of this case. Choose one of: {files}.")
        key = chosen[0].value_key
        winning = [e for e in result.evidence if e.value_key == key]
        losing = [e for e in result.evidence if e.value_key != key]
        rationale = f"override: {path} is the source of truth"
    else:
        return Ruling(False, f"Unknown ruling `{verb}`.")

    top = min(winning, key=lambda e: e.authority)
    store.record_decision(
        case_id,
        user,
        verb,
        top.value_key,
        [e.source_id for e in winning],
        [e.source_id for e in losing],
        rationale,
    )
    store.set_state(case_id, "DECIDED")
    edits = _edits(losing)
    return Ruling(
        True,
        f"Recorded: {user} chose **{verb}** on `{case_id}`. Truth: `{top.value_key}` "
        f'("{top.value_text}", {top.path}). {len(edits)} passage(s) to fix.',
        truth_value=top.value_key,
        truth_quote=top.quote,
        truth_path=top.path,
        edits=edits,
    )

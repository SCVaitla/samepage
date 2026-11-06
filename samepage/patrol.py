"""Drift patrol and retest reports.

Patrol re-asks every known question (both agents, sealed), so drift is found before a
customer finds it. Retest re-asks a fixed case's question and paraphrases against the
fix branch and shows before/after. This module only builds reports from results; the
arbiter does the asking.
"""

from __future__ import annotations

from dataclasses import dataclass

from samepage.cards import BADGE, blast_radius
from samepage.models import CaseResult, Outcome


@dataclass(frozen=True)
class PatrolItem:
    question: str
    result: CaseResult
    case_id: str | None  # set when the patrol opened a case for an alarm


def patrol_report(items: list[PatrolItem], ref: str, arbiter: str) -> str:
    alarms = [i for i in items if i.result.outcome.is_alarm]
    lines = [
        f"#### Drift patrol on `{ref}`: {len(items)} question(s) checked, **{len(alarms)} alarm(s)**",
        "",
    ]
    for item in sorted(items, key=lambda i: (not i.result.outcome.is_alarm, i.question)):
        badge = BADGE[item.result.outcome]
        tail = ""
        if item.case_id:
            radius = blast_radius(item.result)
            tail = f": case `{item.case_id}`, wrong value in {len(radius)} place(s)"
        lines.append(f"- {badge}: {item.question}{tail}")
    if alarms:
        lines += ["", f"Open a case with `@{arbiter} show <case>` to see the evidence and rule on it."]
    return "\n".join(lines)


def headline_values(result: CaseResult) -> dict[str, str]:
    """Each agent's headline value key ('' if it had none)."""
    out: dict[str, str] = {agent: "" for agent in result.answers}
    for c in result.checked:
        if c.verified and not out.get(c.agent):
            out[c.agent] = c.value_key
    return out


def consistent(result: CaseResult, truth: str) -> bool:
    """Both agents gave the same verified answer, and it is the approved truth."""
    values = headline_values(result)
    return len(values) >= 2 and all(v == truth for v in values.values())


@dataclass(frozen=True)
class RetestRow:
    question: str
    before: CaseResult
    after: CaseResult


def retest_summary(rows: list[RetestRow], truth: str) -> dict[str, object]:
    before = sum(consistent(r.before, truth) for r in rows)
    after = sum(consistent(r.after, truth) for r in rows)
    return {
        "questions": len(rows),
        "consistent_before": before,
        "consistent_after": after,
        "all_fixed": bool(rows) and after == len(rows),
    }


def retest_card(case_id: str, ref: str, rows: list[RetestRow], truth: str) -> str:
    s = retest_summary(rows, truth)
    lines = [
        f"#### Retest for case `{case_id}` on `{ref}`",
        f"Truth: `{truth}`. Both agents right and in agreement: "
        f"**{s['consistent_before']}/{s['questions']} before → {s['consistent_after']}/{s['questions']} after**",
        "",
        "| Question | Before (main) | After (fix branch) |",
        "|---|---|---|",
    ]
    for r in rows:

        def cell(res: CaseResult) -> str:
            vals = ", ".join(f"{a}: {v or '—'}" for a, v in sorted(headline_values(res).items()))
            mark = ":white_check_mark:" if consistent(res, truth) else ":x:"
            return f"{mark} {res.outcome.value} ({vals})"

        lines.append(f"| {r.question} | {cell(r.before)} | {cell(r.after)} |")
    verdict = (
        f"{BADGE[Outcome.RESOLVED]}. The fix works. A human can merge the PR."
        if s["all_fixed"]
        else "Not resolved yet: some answers are still wrong or inconsistent."
    )
    lines += ["", verdict]
    return "\n".join(lines)

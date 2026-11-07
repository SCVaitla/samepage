"""Render what the room sees: the investigation card, with blast radius and owner routing.

Cards are Markdown, which Mattermost renders. Quotes come from the corpus or from
verified agent claims only, and are shown as quotes (data), never as instructions.
"""

from __future__ import annotations

from samepage.models import CaseResult, Evidence, Outcome

BADGE = {
    Outcome.VERIFIED: ":white_check_mark: VERIFIED",
    Outcome.COMPATIBLE: ":ok: COMPATIBLE",
    Outcome.CONFLICT: ":rotating_light: CONFLICT",
    Outcome.SOURCE_CONFLICT: ":warning: SOURCE_CONFLICT · consensus trap (agents agree, docs don't)",
    Outcome.UNSUPPORTED: ":grey_question: UNSUPPORTED",
    Outcome.RESOLVED: ":heavy_check_mark: RESOLVED",
}
MAX_QUOTE = 220


def _q(text: str) -> str:
    text = text.replace("`", "'")
    return text if len(text) <= MAX_QUOTE else text[: MAX_QUOTE - 3] + "..."


def _loc(e: Evidence) -> str:
    span = f"L{e.line_start}" if e.line_start == e.line_end else f"L{e.line_start}-{e.line_end}"
    return f"`{e.path}` {span}"


def blast_radius(result: CaseResult) -> list[Evidence]:
    """Every place the losing value(s) appear, deduplicated by file and line."""
    if result.proposal is None:
        return []
    seen: set[tuple[str, int]] = set()
    out = []
    for e in sorted(result.proposal.losing, key=lambda e: (e.authority, e.path, e.line_start)):
        if (e.path, e.line_start) not in seen:
            seen.add((e.path, e.line_start))
            out.append(e)
    return out


def owners_to_notify(result: CaseResult) -> list[str]:
    """Owners of the sources on the losing side: they get @mentioned and may rule."""
    return sorted({e.owner for e in blast_radius(result) if e.owner})


def investigation_card(case_id: str, result: CaseResult, arbiter: str) -> str:
    lines = [
        f"#### SamePage case `{case_id}`: {BADGE[result.outcome]}",
        f"**Question:** {result.question}",
        "",
    ]
    if result.answers:
        lines.append("**Sealed answers (revealed together)**")
        for agent, text in sorted(result.answers.items()):
            lines.append(f"- **{agent}:** {_q(text)}")
        lines.append("")
    lines += ["**Why:** " + " ".join(result.reasons), ""]

    if result.outcome.is_alarm and result.proposal is not None:
        p = result.proposal
        lines += [
            "**Evidence**",
            "",
            "| Says | Where | Source (authority) | Found by | Quote |",
            "|---|---|---|---|---|",
        ]
        for e in sorted(result.evidence, key=lambda e: (e.value_key != p.value_key, e.authority, e.path)):
            lines.append(
                f'| {e.value_key} | {_loc(e)} | {e.source_id} ({e.authority}) | {e.found_by} | "{_q(e.quote)}" |'
            )
        radius = blast_radius(result)
        lines += [
            "",
            f"**Blast radius:** the disputed value appears in **{len(radius)}** place(s) "
            f"across **{len({e.source_id for e in radius})}** team(s):",
        ]
        for e in radius:
            lines.append(f"- {_loc(e)}: read by {e.surface or e.source_id} (owner {e.owner or 'unassigned'})")
        lines += ["", f"**Proposed truth (advice, you decide):** `{p.value_key}`, because {p.because}"]
        owners = owners_to_notify(result)
        if owners:
            lines.append("**Owners asked to rule:** " + " ".join(owners))
        lines += [
            "",
            f"Rule by replying here (no @mention needed): `approve {case_id}` (accept the proposal), "
            f"`override {case_id} <file>` (that file is the truth), or `reject {case_id} <reason>`.",
        ]
    elif result.evidence:
        lines.append("**Evidence**")
        for e in result.evidence:
            lines.append(f'- {_loc(e)} ({e.source_id}): "{_q(e.quote)}"')
    unverified = [c for c in result.checked if not c.verified]
    if unverified:
        lines += ["", "**Claims dropped (quote not verified):**"]
        lines += [f"- {c.agent}: {c.reason}" for c in unverified]
    if result.injections:
        lines += ["", ":shield: **Ignored text that reads like instructions to AI agents** (docs are data):"]
        lines += [f'- `{i.path}` L{i.line}: "{_q(i.text)}"' for i in result.injections]
    return "\n".join(lines)

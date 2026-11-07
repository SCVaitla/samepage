"""Resolution receipt: one card that sums up a resolved case, built only from stored records.

Nothing here is computed fresh: answers, evidence, owners, the ruling, the PR and the retest
all come from the database (the audit log's tables). If a piece is missing, the receipt says so.
"""

from __future__ import annotations

import json
from typing import Any

from samepage.models import Outcome
from samepage.store import Store

CONSENSUS_TRAP = (
    "**Consensus trap caught:** both agents agreed, but company docs still say otherwise. "
    "Agreement alone is not proof, so SamePage checked the evidence anyway."
)


def latest_retest(store: Store, case_id: str) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT ref, results_json, at FROM retest_runs WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,)
    ).fetchone()
    if row is None:
        return None
    return {"ref": row["ref"], "at": row["at"], **json.loads(row["results_json"])}


def resolution_receipt(store: Store, case_id: str) -> str:
    case = store.case(case_id)
    result = store.result(case_id)
    if case is None or result is None:
        return f"No case `{case_id}`."
    decision = store.decision_for(case_id)
    pr = store.fix_pr(case_id)
    retest = latest_retest(store, case_id)
    lines = [f"#### 🧾 SamePage resolution receipt: case `{case_id}` · {case['state']}", ""]
    lines.append(f"**Question:** {case['question']}")
    lines.append("")
    lines.append("**Sealed answers**")
    for agent, text in result.answers.items():
        lines.append(f"- **{agent}:** {text}")
    lines.append("")
    if result.outcome is Outcome.SOURCE_CONFLICT:
        lines += [CONSENSUS_TRAP, ""]
    else:
        lines += [f"**Found:** {result.outcome.value}. " + " ".join(result.reasons), ""]
    losing = result.proposal.losing if result.proposal else []
    if losing:
        lines.append("**Docs that were wrong**")
        for e in losing:
            lines.append(f"- `{e.path}` L{e.line_start}-{e.line_end}: read by {e.surface} (owner {e.owner})")
        lines.append("")
    if decision is not None:
        lines.append(
            f"**Ruling:** {decision['choice']} by {decision['decided_by']} at {decision['decided_at']}, "
            f"truth `{decision['truth_value']}`"
        )
    else:
        lines.append("**Ruling:** none recorded yet")
    lines.append(f"**Pull request:** {pr['url']} ({pr['status']})" if pr is not None else "**Pull request:** none yet")
    if retest is not None:
        n = retest.get("questions", 0)
        lines.append(
            f"**Retest on `{retest['ref']}`:** {retest.get('consistent_before', 0)}/{n} before → "
            f"{retest.get('consistent_after', 0)}/{n} after (both agents right and in agreement)"
        )
    else:
        lines.append("**Retest:** not run yet")
    lines += ["", "Every line above comes from the append-only audit records. A human merges the PR."]
    return "\n".join(lines)

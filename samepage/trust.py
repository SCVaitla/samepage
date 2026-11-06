"""Source trust ledger: which docs keep losing human rulings.

Built only from recorded decisions (approve/override). A source that loses often is
where knowledge rots, which tells a company which team's docs need attention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from samepage.store import Store


@dataclass(frozen=True)
class TrustRow:
    source_id: str
    wins: int
    losses: int

    @property
    def rulings(self) -> int:
        return self.wins + self.losses

    @property
    def loss_rate(self) -> float:
        return self.losses / self.rulings if self.rulings else 0.0


def ledger(store: Store) -> list[TrustRow]:
    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for d in store.decisions():
        if d["choice"] == "reject":
            continue
        for s in json.loads(d["winners_json"]):
            wins[s] = wins.get(s, 0) + 1
        for s in json.loads(d["losers_json"]):
            losses[s] = losses.get(s, 0) + 1
    sources = set(wins) | set(losses)
    rows = [TrustRow(s, wins.get(s, 0), losses.get(s, 0)) for s in sources]
    return sorted(rows, key=lambda r: (-r.loss_rate, -r.losses, r.source_id))


def render(rows: list[TrustRow]) -> str:
    if not rows:
        return "#### Source trust ledger\nNo rulings yet. The ledger fills in as owners rule on cases."
    lines = ["#### Source trust ledger", "| Source | Lost | Won | Loss rate |", "|---|---|---|---|"]
    for r in rows:
        flag = " :warning:" if r.losses >= 2 and r.loss_rate >= 0.5 else ""
        lines.append(f"| {r.source_id}{flag} | {r.losses} | {r.wins} | {r.loss_rate:.0%} |")
    worst = rows[0]
    if worst.losses:
        lines.append(f"\nMost often wrong: **{worst.source_id}** ({worst.losses} of {worst.rulings} rulings lost).")
    return "\n".join(lines)

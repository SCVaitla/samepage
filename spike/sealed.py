"""Phase 0 spike: the pure (no network) logic of the SamePage Arbiter.

The arbiter reacts to Switch room events. This module turns one event into a
list of actions ("post this text in that room", "record this evidence") and
keeps the state of each case. Keeping it free of I/O means it can be tested
without a Switch server, and the same shape carries into Slice D.

Sealing: each worker answers in its own private desk room. The arbiter records
each answer's hash and arrival time, and only reveals answers in the ask room
once every desk has answered. Workers cannot read each other's desks because
Switch only lets an agent read rooms it is a member of.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MARKER = "[samepage]"  # every arbiter post starts with this, so we ignore our own echoes
CASE_TAG = re.compile(r"\[case ([0-9a-f]{8})\]")


@dataclass(frozen=True)
class Desk:
    worker: str  # the worker agent's Switch name, e.g. "samepage-claude"
    room_id: str


@dataclass(frozen=True)
class Post:
    room_id: str
    body: str


@dataclass(frozen=True)
class Record:
    """One line of evidence for docs/evidence/phase0-events.jsonl."""

    kind: str
    data: dict[str, Any]


Action = Post | Record


@dataclass
class Case:
    case_id: str
    question: str
    asked_by: str
    dispatched_at: str
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)  # worker -> sealed answer
    revealed_at: str | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_mentions(body: str) -> str:
    """'@samepage-arbiter ask X' -> 'ask X'. Drops leading @mentions only."""
    words = body.strip().split()
    while words and words[0].startswith("@"):
        words.pop(0)
    return " ".join(words)


def parse_command(body: str) -> tuple[str, str]:
    """Split an addressed message into (verb, rest). Unknown verbs are returned as-is."""
    text = strip_mentions(body)
    verb, _, rest = text.partition(" ")
    return verb.lower(), rest.strip()


class Arbiter:
    def __init__(self, ask_room: str, desks: list[Desk], self_name: str) -> None:
        self.ask_room = ask_room
        self.desks = {d.room_id: d for d in desks}
        self.self_name = self_name
        self.cases: dict[str, Case] = {}

    # ---- entry point -------------------------------------------------------

    def on_event(self, event: dict[str, Any]) -> list[Action]:
        if event.get("type") != "message":
            return []
        payload = event.get("payload") or {}
        body = str(payload.get("body") or "")
        if body.startswith(MARKER) or payload.get("sender_name") == self.self_name:
            return []  # our own post coming back to us
        room_id = event.get("room_id")
        if room_id == self.ask_room and payload.get("addressed"):
            return self._on_ask_room_command(payload, body)
        if room_id in self.desks:
            return self._on_desk_message(self.desks[room_id], payload, body)
        return []

    # ---- ask room ----------------------------------------------------------

    def _on_ask_room_command(self, payload: dict[str, Any], body: str) -> list[Action]:
        verb, rest = parse_command(body)
        who = str(payload.get("sender_name") or payload.get("sender") or "unknown")
        if verb == "ask" and rest:
            return self._dispatch(rest, who)
        if verb in ("approve", "reject"):
            return self._decide(verb, rest, payload, who)
        return [Post(self.ask_room, f"{MARKER} Commands: `ask <question>`, `approve <case>`, `reject <case>`.")]

    def _dispatch(self, question: str, who: str) -> list[Action]:
        case = Case(uuid.uuid4().hex[:8], question, who, now_iso())
        self.cases[case.case_id] = case
        actions: list[Action] = [
            Record("dispatched", {"case_id": case.case_id, "question": question,
                                  "asked_by": who, "at": case.dispatched_at,
                                  "desks": [d.worker for d in self.desks.values()]}),
            Post(self.ask_room, f"{MARKER} Case `{case.case_id}`: asked "
                                f"{len(self.desks)} agents separately. Answers stay sealed until all reply."),
        ]
        for desk in self.desks.values():
            actions.append(Post(desk.room_id, f"@{desk.worker} [case {case.case_id}] {question}"))
        return actions

    def _decide(self, verb: str, rest: str, payload: dict[str, Any], who: str) -> list[Action]:
        case_id, _, reason = rest.partition(" ")
        case = self.cases.get(case_id)
        if case is None:
            return [Post(self.ask_room, f"{MARKER} No case `{case_id}`.")]
        if case.revealed_at is None:
            return [Post(self.ask_room, f"{MARKER} Case `{case_id}` is not revealed yet; nothing to rule on.")]
        decision = {"case_id": case_id, "choice": verb, "reason": reason.strip(),
                    "decided_by": who, "sender_id": payload.get("sender"),
                    "message_id": payload.get("message_id"), "at": now_iso()}
        return [Record("decision", decision),
                Post(self.ask_room, f"{MARKER} Recorded: {who} chose **{verb}** on case `{case_id}`.")]

    # ---- desk rooms --------------------------------------------------------

    def _on_desk_message(self, desk: Desk, payload: dict[str, Any], body: str) -> list[Action]:
        match = CASE_TAG.search(body) or re.search(r'"case_id"\s*:\s*"([0-9a-f]{8})"', body)
        if match is None:
            return []
        case = self.cases.get(match.group(1))
        if case is None or desk.worker in case.answers or case.revealed_at is not None:
            return []  # unknown case, or not the first answer: only the first answer is sealed
        sealed = {"case_id": case.case_id, "worker": desk.worker, "desk_room": desk.room_id,
                  "sender": payload.get("sender"), "sender_name": payload.get("sender_name"),
                  "message_id": payload.get("message_id"), "server_ts_ms": payload.get("timestamp"),
                  "sealed_at": now_iso(), "sha256": sha256(body), "body": body}
        case.answers[desk.worker] = sealed
        actions: list[Action] = [Record("sealed", {k: v for k, v in sealed.items() if k != "body"})]
        if len(case.answers) == len(self.desks):
            actions += self._reveal(case)
        return actions

    def _reveal(self, case: Case) -> list[Action]:
        case.revealed_at = now_iso()
        lines = [f"{MARKER} Case `{case.case_id}` — sealed answers revealed together",
                 f"Question: {case.question}", ""]
        for worker, ans in case.answers.items():
            lines += [f"**{worker}** (sealed {ans['sealed_at']}, sha256 `{ans['sha256'][:12]}`)",
                      ans["body"][:1500], ""]
        lines.append(f"Rule with `@{self.self_name} approve {case.case_id}` or "
                     f"`@{self.self_name} reject {case.case_id}`")
        return [Record("revealed", {"case_id": case.case_id, "at": case.revealed_at,
                                    "sealed": {w: a["sha256"] for w, a in case.answers.items()}}),
                Post(self.ask_room, "\n".join(lines))]


def verify_ordering(records: list[dict[str, Any]]) -> list[str]:
    """Check the evidence log: every answer was sealed after dispatch and before reveal.

    Returns a list of problems; an empty list means the ordering holds.
    """
    problems: list[str] = []
    by_case: dict[str, dict[str, Any]] = {}
    for r in records:
        entry = by_case.setdefault(r["case_id"], {"sealed": []})
        if r["kind"] == "sealed":
            entry["sealed"].append(r)
        else:
            entry[r["kind"]] = r
    for case_id, e in by_case.items():
        if "revealed" not in e:
            continue
        if "dispatched" not in e:
            problems.append(f"{case_id}: revealed without a dispatch record")
            continue
        for s in e["sealed"]:
            if not (e["dispatched"]["at"] <= s["sealed_at"] <= e["revealed"]["at"]):
                problems.append(f"{case_id}: {s['worker']} sealed outside dispatch..reveal")
        if sorted(e["revealed"]["sealed"].values()) != sorted(s["sha256"] for s in e["sealed"]):
            problems.append(f"{case_id}: revealed hashes differ from sealed hashes")
    return problems

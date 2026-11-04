"""Unit tests for the Phase 0 spike logic. No network: events are built by hand
in the envelope shape documented in Switch's agent-protocol.md (event catalog)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arbiter_spike import parse_sse  # noqa: E402
from sealed import MARKER, Arbiter, Desk, Post, Record, parse_command, verify_ordering  # noqa: E402

ASK, DESK_A, DESK_B = "room-ask", "room-a", "room-b"


def msg(room: str, body: str, sender: str = "@switch-user-1:localhost",
        name: str = "dev", addressed: bool = True) -> dict[str, Any]:
    return {"type": "message", "room_id": room, "sequence": 1,
            "payload": {"addressed": addressed, "sender": sender, "sender_name": name,
                        "message_id": "m1", "body": body, "timestamp": 0, "attachments": []}}


def make() -> Arbiter:
    return Arbiter(ASK, [Desk("samepage-claude", DESK_A), Desk("samepage-codex", DESK_B)], "samepage-arbiter")


def ask(arb: Arbiter, question: str = "Does Starter include SSO?") -> str:
    actions = arb.on_event(msg(ASK, f"@samepage-arbiter ask {question}"))
    dispatched = [a for a in actions if isinstance(a, Record) and a.kind == "dispatched"]
    assert len(dispatched) == 1
    return str(dispatched[0].data["case_id"])


def test_parse_command_strips_leading_mentions() -> None:
    assert parse_command("@samepage-arbiter approve abc12345 spec wins") == ("approve", "abc12345 spec wins")
    assert parse_command("@SamePage-Arbiter ASK is it free?") == ("ask", "is it free?")


def test_ask_dispatches_one_addressed_message_per_desk_and_reveals_nothing() -> None:
    arb = make()
    actions = arb.on_event(msg(ASK, "@samepage-arbiter ask Does Starter include SSO?"))
    desk_posts = [a for a in actions if isinstance(a, Post) and a.room_id != ASK]
    assert {p.room_id for p in desk_posts} == {DESK_A, DESK_B}
    assert any(p.body.startswith("@samepage-claude [case ") for p in desk_posts)
    assert any(p.body.startswith("@samepage-codex [case ") for p in desk_posts)
    ask_posts = [a for a in actions if isinstance(a, Post) and a.room_id == ASK]
    assert all("revealed" not in p.body for p in ask_posts)


def test_answers_stay_sealed_until_every_desk_has_answered() -> None:
    arb = make()
    case_id = ask(arb)
    first = arb.on_event(msg(DESK_A, f'```json\n{{"case_id": "{case_id}", "answer": "Yes"}}\n```', name="samepage-claude"))
    assert [a.kind for a in first if isinstance(a, Record)] == ["sealed"]
    assert not any(isinstance(a, Post) and a.room_id == ASK for a in first)

    second = arb.on_event(msg(DESK_B, f'```json\n{{"case_id": "{case_id}", "answer": "No"}}\n```', name="samepage-codex"))
    kinds = [a.kind for a in second if isinstance(a, Record)]
    assert kinds == ["sealed", "revealed"]
    reveal = [a for a in second if isinstance(a, Post) and a.room_id == ASK][0]
    assert '"answer": "Yes"' in reveal.body and '"answer": "No"' in reveal.body


def test_only_first_answer_per_desk_is_sealed() -> None:
    arb = make()
    case_id = ask(arb)
    arb.on_event(msg(DESK_A, f"[case {case_id}] first"))
    again = arb.on_event(msg(DESK_A, f"[case {case_id}] changed my mind"))
    assert again == []
    assert "first" in arb.cases[case_id].answers["samepage-claude"]["body"]


def test_own_posts_and_unknown_cases_are_ignored() -> None:
    arb = make()
    assert arb.on_event(msg(ASK, f"{MARKER} anything")) == []
    assert arb.on_event(msg(DESK_A, "[case deadbeef] stray")) == []
    assert arb.on_event({"type": "room_join", "room_id": ASK, "payload": {}}) == []


def test_unaddressed_ask_room_chatter_is_ignored() -> None:
    assert make().on_event(msg(ASK, "ask whether we ship friday", addressed=False)) == []


def test_approval_records_who_and_when_only_after_reveal() -> None:
    arb = make()
    case_id = ask(arb)
    early = arb.on_event(msg(ASK, f"@samepage-arbiter approve {case_id}"))
    assert not any(isinstance(a, Record) for a in early)

    arb.on_event(msg(DESK_A, f"[case {case_id}] a"))
    arb.on_event(msg(DESK_B, f"[case {case_id}] b"))
    actions = arb.on_event(msg(ASK, f"@samepage-arbiter approve {case_id} spec is source of truth",
                               sender="@switch-user-7:localhost", name="dev"))
    decision = [a for a in actions if isinstance(a, Record)][0]
    assert decision.kind == "decision"
    assert decision.data["choice"] == "approve"
    assert decision.data["decided_by"] == "dev"
    assert decision.data["sender_id"] == "@switch-user-7:localhost"
    assert decision.data["reason"] == "spec is source of truth"


def test_verify_ordering_accepts_a_real_sequence_and_flags_tampering() -> None:
    arb = make()
    case_id = ask(arb)
    rows: list[dict[str, Any]] = []
    for room, body in ((None, None), (DESK_A, f"[case {case_id}] a"), (DESK_B, f"[case {case_id}] b")):
        if room is None:
            continue
        rows += [{"kind": a.kind, **a.data} for a in arb.on_event(msg(room, body)) if isinstance(a, Record)]
    dispatched = {"kind": "dispatched", "case_id": case_id, "at": arb.cases[case_id].dispatched_at}
    rows = [dispatched, *rows]
    assert verify_ordering(rows) == []

    tampered = [dict(r) for r in rows]
    for r in tampered:
        if r["kind"] == "sealed":
            r["sealed_at"] = "2999-01-01T00:00:00.000+00:00"
            break
    assert verify_ordering(tampered)


def test_parse_sse_handles_ids_comments_and_multiline_data() -> None:
    raw = [": keepalive", "", "event: connection_state", 'data: {"cursor": 0}', "",
           "id: 4813", "event: message", 'data: {"a":', "data: 1}", ""]
    frames = list(parse_sse(iter(raw)))
    assert frames == [
        {"id": None, "event": "connection_state", "data": '{"cursor": 0}'},
        {"id": "4813", "event": "message", "data": '{"a":\n1}'},
    ]

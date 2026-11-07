"""The arbiter end to end, with a fake Switch room, fake agents and a fake GitHub.

Flow: ask -> sealed answers -> CONFLICT card -> approve -> fix brief -> fixer reports a PR
-> diff guard -> retest on the fix branch -> RESOLVED. The fake agents answer from the
corpus as it is at the requested ref, citing real lines. The arbiter and engine are real.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from samepage.arbiter import Arbiter
from samepage.config import Settings
from samepage.corpus import Corpus
from samepage.github import PullRequest
from samepage.store import Store
from samepage.text import Glossary
from tests.helpers import CORPUS_DIR, ROOT, span_of

ASK, FIX = "room-ask", "room-fix"
DESKS = {"samepage-claude": "room-desk-a", "samepage-codex": "room-desk-b"}
BRANCH_FIXES = {
    "website/faq.md": (
        "Yes. Single sign-on is included on all plans, so your team",
        "No. Single sign-on is available on the Enterprise plan only, so your team",
    ),
    "sales/faq.md": (
        "Yes. Starter can enable SSO from the admin settings, so small teams",
        "No. SSO is available on the Enterprise plan only, so small teams",
    ),
}


def build_corpus(ref: str) -> Corpus:
    texts = {p.relative_to(CORPUS_DIR).as_posix(): p.read_text() for p in CORPUS_DIR.rglob("*.md")}
    if ref != "main":
        for path, (old, new) in BRANCH_FIXES.items():
            assert old in texts[path]
            texts[path] = texts[path].replace(old, new)
    return Corpus._build(texts, (CORPUS_DIR / "sources.yaml").read_text(), Glossary.load(CORPUS_DIR / "glossary.yaml"))


CORPORA = {"main": build_corpus("main"), "samepage-fix": build_corpus("fix")}


def corpus_for(ref: str) -> Corpus:
    return CORPORA["main"] if ref in ("main", "holdout/h1") else CORPORA["samepage-fix"]


# What each fake worker cites, by topic and ref. claude reads the public docs, codex the spec.
KNOWLEDGE: dict[tuple[str, str, bool], tuple[str, str, str, str, str, str]] = {
    ("samepage-claude", "sso", False): (
        "website/faq.md",
        "Single sign-on is included on all plans",
        "true",
        "sso",
        "available_on_plan",
        "starter",
    ),
    ("samepage-claude", "sso", True): (
        "website/faq.md",
        "Single sign-on is available on the Enterprise plan only",
        "false",
        "sso",
        "available_on_plan",
        "starter",
    ),
    ("samepage-codex", "sso", False): (
        "product_spec.md",
        "Single sign-on (SSO) through SAML 2.0 is an Enterprise plan feature",
        "false",
        "sso",
        "available_on_plan",
        "starter",
    ),
    ("samepage-claude", "refund", False): (
        "support/macros.md",
        "refunds are available within 30 days of purchase",
        "30 days",
        "refund",
        "window",
        "",
    ),
    ("samepage-codex", "refund", False): (
        "product_spec.md",
        "a customer may request a full refund within 14 days",
        "14 days",
        "refund",
        "window",
        "",
    ),
    ("samepage-claude", "seat", False): (
        "website/pricing.md",
        "Up to 10 seats per workspace",
        "10",
        "seats",
        "limit",
        "starter",
    ),
    ("samepage-codex", "seat", False): (
        "website/faq.md",
        "A Starter workspace can have up to 10 seats",
        "10",
        "seats",
        "limit",
        "starter",
    ),
}
TOPICS = {"sso": ("sso", "single sign"), "refund": ("refund", "money back"), "seat": ("seat", "member", "users")}


def fake_answer(worker: str, question: str, ref: str, qid: str) -> str:
    topic = next((t for t, words in TOPICS.items() if any(w in question.lower() for w in words)), "")
    fact = KNOWLEDGE.get((worker, topic, ref != "main")) or KNOWLEDGE.get((worker, topic, False))
    if fact is None:
        body = {"question_id": qid, "answer": "The docs do not say.", "claims": [], "unknown": True}
    else:
        path, quote, value, entity, attribute, qualifier = fact
        start, end = span_of(path, quote, corpus_for(ref))
        body = {
            "question_id": qid,
            "answer": value,
            "confidence": "high",
            "unknown": False,
            "claims": [
                {
                    "entity": entity,
                    "attribute": attribute,
                    "qualifier": qualifier,
                    "value": value,
                    "source_path": f"corpus/{path}",
                    "line_start": start,
                    "line_end": end,
                    "quote": quote,
                }
            ],
        }
    return "```json\n" + json.dumps(body) + "\n```"


class FakeSwitch:
    """Records posts; plays the worker agents and the fixer."""

    def __init__(self, silent: set[str] | None = None) -> None:
        self.posts: list[tuple[str, str]] = []
        self.arbiter: Arbiter | None = None
        self.silent = silent or set()
        self.fixer_reply = True

    async def post(self, room_id: str, content: str) -> None:
        self.posts.append((room_id, content))
        for worker, desk in DESKS.items():
            if room_id == desk and content.startswith(f"@{worker} [batch ") and worker not in self.silent:
                asyncio.get_running_loop().create_task(self._worker_reply(worker, desk, content))
        if room_id == FIX and self.fixer_reply:
            case = re.search(r"\[fix ([0-9a-f]{8})\]", content)
            if case:
                reply = f"[fix {case.group(1)}] PR: https://github.com/acme/juniper-docs/pull/7"
                asyncio.get_running_loop().create_task(self._event(FIX, reply, "samepage-fixer"))

    async def _worker_reply(self, worker: str, desk: str, content: str) -> None:
        batch = re.search(r"\[batch ([0-9a-f]{8})\] \[ref ([\w/.-]+)\]", content)
        assert batch is not None
        qs = re.findall(r"^(q\d+): (.+)$", content, re.MULTILINE)
        body = f"[batch {batch.group(1)}]\n" + "\n".join(fake_answer(worker, q, batch.group(2), qid) for qid, q in qs)
        await self._event(desk, body, worker)

    async def _event(self, room: str, body: str, sender: str, addressed: bool = False) -> None:
        assert self.arbiter is not None
        await self.arbiter.on_event(
            {
                "type": "message",
                "room_id": room,
                "sequence": 1,
                "payload": {
                    "addressed": addressed,
                    "sender": f"@switch-{sender}:localhost",
                    "sender_name": sender,
                    "message_id": "m",
                    "body": body,
                    "timestamp": 0,
                },
            }
        )

    async def say(self, text: str, user: str = "dev") -> None:
        await self._event(ASK, f"@samepage-arbiter {text}", user, addressed=True)

    def in_room(self, room: str) -> list[str]:
        return [c for r, c in self.posts if r == room]


class FakeGitHub:
    def __init__(self, diff: str) -> None:
        self.diff = diff

    async def pull_request(self, url: str) -> PullRequest:
        return PullRequest(
            url=url,
            number=7,
            head_ref=self.head,
            head_sha="a" * 40,
            base_ref=self.base,
            state="open",
            merged=False,
            diff=self.diff,
        )

    head = ""
    base = "main"


def settings(tmp_path: Path, **extra: Any) -> Settings:
    values = {
        "SAMEPAGE_ASK_ROOM": ASK,
        "SAMEPAGE_FIX_ROOM": FIX,
        "SAMEPAGE_APPROVERS": "dev",
        "SAMEPAGE_DESKS": ",".join(f"{w}={r}" for w, r in DESKS.items()),
        "SAMEPAGE_GOLDEN": str(ROOT / "eval/golden.yaml"),
        "SAMEPAGE_REPORTS_DIR": str(tmp_path / "reports"),
        "SAMEPAGE_AGENT_TIMEOUT": 5,
        "SAMEPAGE_RETEST_QUESTIONS": 3,
        **extra,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


async def drain() -> None:
    for _ in range(200):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def diff_for(lines: dict[str, list[int]]) -> str:
    parts = []
    for path, numbers in lines.items():
        parts.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}")
        for n in numbers:
            parts.append(f"@@ -{n},1 +{n},1 @@\n-old\n+new")
    return "\n".join(parts) + "\n"


def make(tmp_path: Path, diff: str = "", **extra: Any) -> tuple[Arbiter, FakeSwitch, FakeGitHub]:
    sw = FakeSwitch()
    gh = FakeGitHub(diff)
    arb = Arbiter(settings(tmp_path, **extra), sw, Store(tmp_path / "db.sqlite"), corpus_for=corpus_for, github=gh)  # type: ignore[arg-type]
    sw.arbiter = arb
    return arb, sw, gh


def test_full_flow_ask_conflict_approve_pr_retest_resolved(tmp_path: Path) -> None:
    faq_line = span_of("website/faq.md", "Single sign-on is included on all plans")[0]
    sales_line = span_of("sales/faq.md", "Starter can enable SSO from the admin settings")[0]
    arb, sw, gh = make(tmp_path, diff_for({"website/faq.md": [faq_line], "sales/faq.md": [sales_line]}))

    async def scenario() -> None:
        await sw.say("ask Does the Starter plan include single sign-on?")
        await drain()
        card = sw.in_room(ASK)[-1]
        assert "CONFLICT" in card and "Blast radius" in card and "@marketing-lead" in card and "@sales-lead" in card
        case_id = re.search(r"case `([0-9a-f]{8})`", card).group(1)  # type: ignore[union-attr]
        # Both desks got the same question; neither desk saw the other's answer.
        assert all(len(sw.in_room(r)) == 1 for r in DESKS.values())
        gh.head = f"samepage/{case_id}"
        await sw.say(f"approve {case_id} spec is the source of truth")
        await drain()
        brief = sw.in_room(FIX)[0]
        assert "website/faq.md" in brief and "sales/faq.md" in brief and "Do NOT merge" in brief
        retest = next(c for c in sw.in_room(ASK) if "Retest for case" in c)
        assert "0/3 before → 3/3 after" in retest
        assert arb.store.case(case_id)["state"] == "RESOLVED"  # type: ignore[index]
        receipt = next(c for c in sw.in_room(ASK) if "resolution receipt" in c)
        assert "0/3 before → 3/3 after" in receipt and "approve by" in receipt and "/pull/" in receipt
        types = [e["type"] for e in arb.store.history(case_id)]
        for expected in (
            "case_opened",
            "answer_sealed",
            "revealed",
            "classified",
            "decision",
            "fix_requested",
            "fix_pr",
            "retest",
        ):
            assert expected in types, expected
        await sw.say("trust")
        await drain()
        assert "website" in sw.in_room(ASK)[-1] and "Lost" in sw.in_room(ASK)[-1]
        await sw.say(f"history {case_id}")
        await sw.say("history single sign-on")
        await sw.say(f"show {case_id}")
        await drain()
        assert "History of case" in sw.in_room(ASK)[-3] and case_id in sw.in_room(ASK)[-2]

    asyncio.run(scenario())


def test_pr_touching_other_lines_is_refused_and_not_retested(tmp_path: Path) -> None:
    arb, sw, gh = make(tmp_path, diff_for({"website/pricing.md": [3]}))

    async def scenario() -> None:
        await sw.say("ask Is SSO available on Starter?")
        await drain()
        case_id = re.search(r"case `([0-9a-f]{8})`", sw.in_room(ASK)[-1]).group(1)  # type: ignore[union-attr]
        gh.head = f"samepage/{case_id}"
        await sw.say(f"approve {case_id}")
        await drain()
        assert any("failed the safety check" in c and "not approved" in c for c in sw.in_room(ASK))
        assert not any("Retest for case" in c for c in sw.in_room(ASK))
        assert arb.store.fix_pr(case_id)["status"] == "rejected_by_guard"  # type: ignore[index]

    asyncio.run(scenario())


def test_rulings_need_authority_and_support_override_and_reject(tmp_path: Path) -> None:
    _arb, sw, _ = make(tmp_path, SAMEPAGE_FIX_ROOM="")

    async def scenario() -> None:
        await sw.say("ask How many days do customers have to request a refund?")
        await drain()
        case_id = re.search(r"case `([0-9a-f]{8})`", sw.in_room(ASK)[-1]).group(1)  # type: ignore[union-attr]
        await sw.say(f"approve {case_id}", user="mallory")
        await drain()
        assert "can't approve" in sw.in_room(ASK)[-1] and "@support-lead" in sw.in_room(ASK)[-1]
        await sw.say(f"override {case_id} nowhere.md")
        await drain()
        assert "isn't part of this case" in sw.in_room(ASK)[-1]
        await sw.say(f"override {case_id} support/macros.md")
        await drain()
        assert any("Truth: `days:30`" in c for c in sw.in_room(ASK))
        assert "No fix room" in sw.in_room(ASK)[-1]
        await sw.say(f"reject {case_id} already ruled")
        await drain()
        assert "nothing to rule on" in sw.in_room(ASK)[-1]

    asyncio.run(scenario())


def test_owner_of_a_losing_source_may_rule(tmp_path: Path) -> None:
    _arb, sw, _ = make(tmp_path, SAMEPAGE_APPROVERS="", SAMEPAGE_FIX_ROOM="")

    async def scenario() -> None:
        await sw.say("ask What is the refund window?")
        await drain()
        case_id = re.search(r"case `([0-9a-f]{8})`", sw.in_room(ASK)[-1]).group(1)  # type: ignore[union-attr]
        await sw.say(f"reject {case_id} macro is being retired", user="support-lead")
        await sw.say(f"override {case_id} support/macros.md", user="support-lead")
        await drain()
        assert "Only an approver can" in sw.in_room(ASK)[-2] and "Only an approver can" in sw.in_room(ASK)[-1]
        await sw.say(f"approve {case_id}", user="support-lead")
        await drain()
        assert any("chose **approve**" in c for c in sw.in_room(ASK))

    asyncio.run(scenario())


def test_silent_agent_times_out_to_unsupported(tmp_path: Path) -> None:
    _arb, sw, _ = make(tmp_path, SAMEPAGE_AGENT_TIMEOUT=0.3)
    sw.silent = {"samepage-codex"}

    async def scenario() -> None:
        await sw.say("ask Does the Starter plan include single sign-on?")
        await drain()
        assert "UNSUPPORTED" in sw.in_room(ASK)[-1] and "timeout" in sw.in_room(ASK)[-1]

    asyncio.run(scenario())


def test_patrol_finds_the_drift_and_records_answers(tmp_path: Path) -> None:
    _arb, sw, _ = make(tmp_path)

    async def scenario() -> None:
        await sw.say("patrol")
        await drain()
        report = sw.in_room(ASK)[-1]
        assert "6 question(s) checked" in report and "3 alarm(s)" in report
        assert list((tmp_path / "reports").glob("answers-*.jsonl"))
        await sw.say("help")
        await sw.say("ask")
        await drain()
        assert "Commands:" in sw.in_room(ASK)[-1]

    asyncio.run(scenario())


def test_own_messages_and_other_rooms_are_ignored(tmp_path: Path) -> None:
    arb, sw, _ = make(tmp_path)

    async def scenario() -> None:
        await sw._event(ASK, "[samepage] echo", "samepage-arbiter", addressed=True)
        await sw._event("room-elsewhere", "@samepage-arbiter ask x", "dev", addressed=True)
        await arb.on_event({"type": "room_join", "room_id": ASK})
        await sw._event(DESKS["samepage-claude"], "[batch deadbeef] stray", "samepage-claude")
        await sw._event(FIX, "[fix deadbeef] PR: https://github.com/acme/juniper-docs/pull/1", "samepage-fixer")
        await drain()
        await sw._event(ASK, "just chatting about ask", "dev")
        await drain()
        assert sw.posts == []

    asyncio.run(scenario())


def test_a_command_without_the_mention_still_works_in_the_ask_room(tmp_path: Path) -> None:
    _arb, sw, _ = make(tmp_path)

    async def scenario() -> None:
        await sw._event(ASK, "help", "dev")
        await drain()
        assert "Commands:" in sw.in_room(ASK)[-1]

    asyncio.run(scenario())


def test_patrol_on_a_ref_and_holdout_ask_the_right_ref(tmp_path: Path) -> None:
    """Only checks routing (which ref and how many questions); H1's content is never asserted on."""
    _arb, sw, _ = make(tmp_path)

    async def scenario() -> None:
        await sw.say("patrol on samepage-fix")
        await drain()
        assert all("[ref samepage-fix]" in c for c in sw.in_room(DESKS["samepage-claude"]))
        await sw.say("patrol holdout")
        await drain()
        assert "[ref holdout/h1]" in sw.in_room(DESKS["samepage-codex"])[-1]
        assert "6 question(s)" in next(c for c in reversed(sw.in_room(ASK)) if "holdout/h1" in c)

    asyncio.run(scenario())


def test_replies_without_an_open_batch_tag_or_from_others_are_dropped(tmp_path: Path) -> None:
    """Review H4/M3: a stale, untagged or foreign reply never lands on a case."""
    arb, sw, _ = make(tmp_path, SAMEPAGE_AGENT_TIMEOUT=0.5)
    sw.silent = {"samepage-claude", "samepage-codex"}

    async def scenario() -> None:
        await sw.say("ask Does the Starter plan include single sign-on?")
        await asyncio.sleep(0.05)
        batch = next(iter(arb.batches))
        good = fake_answer("samepage-claude", "single sign-on", "main", "q1")
        await sw._event(DESKS["samepage-claude"], good, "samepage-claude")  # untagged
        await sw._event(DESKS["samepage-claude"], "[batch deadbeef]\n" + good, "samepage-claude")  # stale tag
        await sw._event(DESKS["samepage-claude"], f"[batch {batch}]\n" + good, "mallory")  # wrong sender
        await sw._event(DESKS["samepage-claude"], f"@samepage-claude [batch {batch}] echo", "")  # our own echo
        await drain()
        card = sw.in_room(ASK)[-1]
        assert "UNSUPPORTED" in card and card.count("timeout") >= 2

    asyncio.run(scenario())


def test_pr_against_another_base_is_refused_and_duplicates_retest_once(tmp_path: Path) -> None:
    faq_line = span_of("website/faq.md", "Single sign-on is included on all plans")[0]
    sales_line = span_of("sales/faq.md", "Starter can enable SSO from the admin settings")[0]
    _arb, sw, gh = make(tmp_path, diff_for({"website/faq.md": [faq_line], "sales/faq.md": [sales_line]}))
    gh.base = "release"

    async def scenario() -> None:
        await sw.say("ask Is SSO available on Starter?")
        await drain()
        case_id = re.search(r"case `([0-9a-f]{8})`", sw.in_room(ASK)[-1]).group(1)  # type: ignore[union-attr]
        gh.head = f"samepage/{case_id}"
        await sw.say(f"approve {case_id}")
        await drain()
        assert any("targets `release`" in c for c in sw.in_room(ASK))
        gh.base = "main"
        reply = f"[fix {case_id}] PR: https://github.com/acme/juniper-docs/pull/7"
        await asyncio.gather(sw._event(FIX, reply, "samepage-fixer"), sw._event(FIX, reply, "samepage-fixer"))
        await drain()
        assert sum("Retest for case" in c for c in sw.in_room(ASK)) == 1
        assert any("[sha " + "a" * 40 + "]" in c for c in sw.in_room(DESKS["samepage-codex"]))

    asyncio.run(scenario())


def test_one_desk_is_not_a_second_opinion(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="at least two desks"):
        make(tmp_path, SAMEPAGE_DESKS="samepage-claude=room-desk-a")

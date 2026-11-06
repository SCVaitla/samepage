"""The SamePage Arbiter: a Switch room participant that runs the whole workflow.

Rooms (ADR 0001):
  ask room    people ask and rule here; sealed answers are revealed here together
  desk rooms  one private room per worker agent; only the arbiter and that worker are members
  fix room    the arbiter and the fixer agent, which opens the PR

Commands, addressed to the arbiter in the ask room (Switch does not forward custom
slash commands to agents, so these are @mentions):
  ask <question> · show <case> · approve <case> [why] · override <case> <file> · reject <case> <why>
  patrol [full] · trust · history <case-or-topic> · help

Every handler runs as its own task, so the event stream keeps flowing while a handler
waits for agents. Any failure is posted to the room; nothing fails silently.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess  # nosec B404 - git fetch with a fixed argument list
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from samepage.cards import investigation_card
from samepage.classify import Engine
from samepage.config import Settings
from samepage.corpus import Corpus
from samepage.decide import Ruling, rule
from samepage.equivalence import QuestionIndex, TfidfEmbedder
from samepage.fixer import branch_for, diff_problems, fix_brief, pr_body
from samepage.github import GitHub
from samepage.golden import load_golden, load_holdout
from samepage.models import AgentAnswer, CaseResult
from samepage.parse import parse_batch, timed_out
from samepage.patrol import PatrolItem, RetestRow, patrol_report, retest_card, retest_summary
from samepage.store import Store
from samepage.trust import ledger
from samepage.trust import render as render_trust

log = logging.getLogger("samepage.arbiter")
MARKER = "[samepage]"
BATCH_TAG = re.compile(r"\[batch ([0-9a-f]{8})\]")
FIX_REPLY = re.compile(r"\[fix ([0-9a-f]{8})\]\s*PR:\s*(\S+)")
CASE_ID = re.compile(r"^[0-9a-f]{8}$")


class Transport(Protocol):
    async def post(self, room_id: str, content: str) -> None: ...


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def strip_mentions(body: str) -> str:
    words = body.strip().split()
    while words and words[0].startswith("@"):
        words.pop(0)
    return " ".join(words)


@dataclass
class Batch:
    batch_id: str
    ref: str
    sha: str | None
    questions: dict[str, str]  # question id -> text
    case_ids: dict[str, str]  # question id -> case id
    futures: dict[str, asyncio.Future[str]] = field(default_factory=dict)  # worker -> raw reply


class Arbiter:
    def __init__(
        self,
        settings: Settings,
        transport: Transport,
        store: Store,
        corpus_for: Callable[[str], Corpus] | None = None,
        github: GitHub | None = None,
    ) -> None:
        self.s = settings
        self.t = transport
        self.store = store
        self.desks = settings.desk_map()
        if len(self.desks) < 2:
            raise ValueError("SamePage needs at least two desks (SAMEPAGE_DESKS): one answer is not a second opinion.")
        self.github = github
        self.corpus_for = corpus_for or self._load_corpus
        self.batches: dict[str, Batch] = {}
        self.pending_fixes: dict[str, Ruling] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        base = self.corpus_for("main")
        self.index = QuestionIndex(TfidfEmbedder(base.glossary), settings.equivalence_threshold)
        self.canonical_text: dict[str, str] = {}
        if settings.golden_path.exists():
            for case in load_golden(settings.golden_path):
                self.canonical_text[case.id] = case.canonical
                for q in case.questions():
                    self.index.add(case.id, q)
        for row in store.questions():
            self.canonical_text.setdefault(row["canonical_id"], row["text"])
            self.index.add(row["canonical_id"], row["text"])

    # ---- corpus at a ref -----------------------------------------------------------

    def _load_corpus(self, ref: str) -> Corpus:
        repo = self.s.docs_repo_dir
        if repo is None:
            return Corpus.from_dir(self.s.corpus_dir)
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin", "--prune"],  # nosec B603 B607
            check=True,
            capture_output=True,
            timeout=60,
        )
        target = ref if re.fullmatch(r"[0-9a-f]{40}", ref) else f"origin/{ref}"
        return Corpus.from_git(repo, target, self.s.docs_subdir)

    def engine(self, ref: str) -> Engine:
        return Engine(self.corpus_for(ref), self.s.quote_slack_lines, self.s.min_anchor_terms)

    # ---- events ---------------------------------------------------------------------

    async def on_event(self, event: dict[str, Any]) -> None:
        if event.get("type") != "message":
            return
        p = event.get("payload") or {}
        body = str(p.get("body") or "")
        if body.startswith(MARKER) or p.get("sender_name") == self.s.switch_agent_name:
            return
        room = event.get("room_id")
        sender, sender_name = str(p.get("sender") or ""), str(p.get("sender_name") or "")
        worker = next((w for w, r in self.desks.items() if r == room), None)
        if worker is not None:
            if self._from_agent(worker, sender, sender_name, body):
                self._on_desk_reply(worker, body)
        elif room == self.s.ask_room and p.get("addressed"):
            ids = [sender_name, sender]
            self._spawn(self._on_command(body, sender_name or sender or "someone", ids))
        elif room == self.s.fix_room and self.s.fix_room:
            m = FIX_REPLY.search(body)
            if m and self._from_agent(self.s.fixer_name, sender, sender_name, body):
                self._spawn(self._on_fix_reply(m.group(1), m.group(2)))

    def _from_agent(self, agent: str, sender: str, sender_name: str, body: str) -> bool:
        """Only the room's own agent may answer there. Our own dispatches echoed back are ignored."""
        if body.lstrip().startswith((f"@{agent} [batch ", f"@{agent} [fix ")):
            return False
        if not self.s.strict_sender:
            return True
        ok = sender_name.lower() == agent.lower() or agent.lower() in sender.lower()
        if not ok:
            log.warning("ignored a message in %s's room from %r (%r)", agent, sender_name, sender)
        return ok

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(self._guard(coro))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _guard(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:  # report every failure in the room (US-9)
            log.exception("handler failed")
            await self.say(f"Something went wrong: {type(exc).__name__}: {exc}. No case was marked verified.")

    async def say(self, text: str, room: str | None = None) -> None:
        await self.t.post(room or self.s.ask_room, f"{MARKER} {text}")

    # ---- commands ---------------------------------------------------------------------

    async def _on_command(self, body: str, user: str, ids: list[str] | None = None) -> None:
        verb, _, rest = strip_mentions(body).partition(" ")
        verb, rest = verb.lower(), rest.strip()
        if verb == "ask" and rest:
            await self.ask(rest, user)
        elif verb in ("approve", "override", "reject"):
            case_id, _, arg = rest.partition(" ")
            await self.decide(case_id, user, verb, arg.strip(), ids or [user])
        elif verb == "show" and CASE_ID.match(rest):
            result = self.store.result(rest)
            await self.say(
                investigation_card(rest, result, self.s.switch_agent_name) if result else f"No case `{rest}`."
            )
        elif verb == "patrol":
            words = rest.split()
            if "holdout" in words:
                await self.patrol_holdout()
            else:
                ref = words[words.index("on") + 1] if "on" in words[:-1] else "main"
                await self.patrol(full="full" in words, ref=ref)
        elif verb == "trust":
            await self.say(render_trust(ledger(self.store)))
        elif verb == "history" and rest:
            await self.say(self.history(rest))
        else:
            n = self.s.switch_agent_name
            await self.say(
                f"Commands: `@{n} ask <question>` · `show <case>` · `approve <case>` · "
                f"`override <case> <file>` · `reject <case> <why>` · `patrol [full]` · `trust` · "
                f"`history <case or topic>`"
            )

    def canonical_for(self, question: str) -> str:
        cid, _ = self.index.best(question)
        if cid is None:
            cid = "Q-" + hashlib.sha256(question.lower().encode()).hexdigest()[:8]
            self.canonical_text.setdefault(cid, question)
        self.index.add(cid, question)
        self.store.add_question(hashlib.sha256(question.encode()).hexdigest()[:12], question, cid)
        return cid

    async def ask(self, question: str, user: str, ref: str = "main") -> tuple[str, CaseResult]:
        canonical = self.canonical_for(question)
        case_id = new_id()
        self.store.create_case(case_id, question, canonical, ref)
        self.store.audit(case_id, "asked", {"by": user})
        await self.say(
            f"Case `{case_id}`: asking {len(self.desks)} agents separately. "
            "Answers stay sealed until all of them reply."
        )
        answers = await self.collect({"q1": question}, {"q1": case_id}, ref)
        result = self.engine(ref).evaluate(question, list(answers["q1"].values()))
        self.store.save_result(case_id, result)
        await self.say(investigation_card(case_id, result, self.s.switch_agent_name))
        return case_id, result

    # ---- sealed collection --------------------------------------------------------------

    async def collect(
        self, questions: dict[str, str], case_ids: dict[str, str], ref: str, sha: str | None = None
    ) -> dict[str, dict[str, AgentAnswer]]:
        """Ask every desk the same questions in parallel; return {question_id: {worker: answer}}.

        Each worker sees only its own desk. The first reply per worker is sealed (hashed and
        stored) before anything is revealed; later replies are ignored.
        """
        out: dict[str, dict[str, AgentAnswer]] = {q: {} for q in questions}
        items = list(questions.items())
        for start in range(0, len(items), max(1, self.s.batch_size)):
            chunk = dict(items[start : start + self.s.batch_size])
            batch = Batch(new_id(), ref, sha, chunk, {q: case_ids[q] for q in chunk})
            loop = asyncio.get_running_loop()
            batch.futures = {w: loop.create_future() for w in self.desks}
            self.batches[batch.batch_id] = batch
            try:
                for worker, room in self.desks.items():
                    await self.t.post(room, self._dispatch_text(worker, batch))
                    self.store.audit(
                        None,
                        "dispatched",
                        {
                            "batch": batch.batch_id,
                            "worker": worker,
                            "ref": ref,
                            "questions": chunk,
                            "cases": batch.case_ids,
                        },
                    )
                for worker, fut in batch.futures.items():
                    try:
                        raw = await asyncio.wait_for(asyncio.shield(fut), timeout=self.s.agent_timeout_s)
                        sealed_at = now_iso()
                        parsed = parse_batch(worker, raw, list(chunk), sealed_at, self.s.max_answer_bytes)
                    except TimeoutError:
                        parsed = {q: timed_out(worker, self.s.agent_timeout_s) for q in chunk}
                    for q, ans in parsed.items():
                        self.store.seal_answer(batch.case_ids[q], ans)
                        out[q][worker] = ans
            finally:
                self.batches.pop(batch.batch_id, None)
            for q in chunk:
                self.store.audit(batch.case_ids[q], "revealed", {"sealed": {w: a.sha256 for w, a in out[q].items()}})
        return out

    def _dispatch_text(self, worker: str, batch: Batch) -> str:
        qs = "\n".join(f"{qid}: {text}" for qid, text in batch.questions.items())
        pin = f" [sha {batch.sha}]" if batch.sha else ""
        at = f"commit `{batch.sha}` of `{batch.ref}`" if batch.sha else f"git ref `{batch.ref}`"
        return (
            f"@{worker} [batch {batch.batch_id}] [ref {batch.ref}]{pin}\n"
            f"Answer each question from the docs at {at}. Start your reply with "
            f"`[batch {batch.batch_id}]`, then one ```json block per question in the Answer Contract, "
            f'with "question_id" set.\n{qs}'
        )

    def _on_desk_reply(self, worker: str, body: str) -> None:
        """A reply counts only if it names a batch that is still waiting. Untagged replies and
        replies to finished batches are dropped, so an answer can never land on the wrong case."""
        m = BATCH_TAG.search(body)
        batch = self.batches.get(m.group(1)) if m else None
        if batch is None:
            log.warning("dropped a reply from %s with no open batch tag", worker)
            return
        fut = batch.futures.get(worker)
        if fut is not None and not fut.done():
            fut.set_result(body)  # first reply only: later ones find the future done

    # ---- rulings, fixes, retests ------------------------------------------------------------

    async def decide(self, case_id: str, user: str, verb: str, arg: str, ids: list[str] | None = None) -> None:
        ruling = rule(self.store, case_id, user, verb, arg, self.s.approver_set(), ids or [user])
        await self.say(ruling.message)
        if not (ruling.ok and ruling.edits):
            return
        row = self.store.case(case_id)
        if row is None:
            raise RuntimeError(f"case {case_id} vanished")
        if not self.s.fix_room:
            await self.say("No fix room is configured, so no PR will be opened (set SAMEPAGE_FIX_ROOM).")
            return
        existing = self.store.fix_pr(case_id)
        if existing is not None:  # idempotent per case
            await self.say(f"Case `{case_id}` already has a fix PR: {existing['url']}")
            return
        self.pending_fixes[case_id] = ruling
        brief = fix_brief(
            case_id, row["question"], ruling, self.s.fixer_name, self.s.github_demo_repo or "the docs repo"
        )
        body = pr_body(case_id, row["question"], ruling, user)
        await self.t.post(self.s.fix_room, f"{brief}\n\nPR body:\n\n{body}")
        self.store.audit(case_id, "fix_requested", {"branch": branch_for(case_id), "edits": len(ruling.edits)})
        await self.say(f"Asked @{self.s.fixer_name} to open a PR on `{branch_for(case_id)}`.")

    async def _on_fix_reply(self, case_id: str, url: str) -> None:
        ruling = self.pending_fixes.pop(case_id, None)  # taken at once: a duplicate reply finds nothing
        if ruling is None:
            return
        if self.github is None:
            await self.say(
                f"Fixer reported {url}, but GITHUB_TOKEN/GITHUB_DEMO_REPO are not set, so SamePage "
                "cannot check the diff. Not retesting an unchecked PR."
            )
            self.pending_fixes[case_id] = ruling
            return
        pr = await self.github.pull_request(url)
        problems = []
        if pr.head_ref != branch_for(case_id):
            problems.append(f"PR branch is `{pr.head_ref}`, expected `{branch_for(case_id)}`")
        if pr.base_ref != "main":
            problems.append(f"PR targets `{pr.base_ref}`, expected `main`")
        if pr.merged or pr.state != "open":
            problems.append(f"PR must be open and unmerged (state {pr.state}, merged {pr.merged})")
        prefix = f"{self.s.docs_subdir.strip('/')}/" if self.s.docs_subdir else ""
        problems += diff_problems(pr.diff, ruling, prefix)
        if problems:
            self.store.save_fix_pr(case_id, pr.url, pr.head_ref, "rejected_by_guard", pr.head_sha)
            self.pending_fixes[case_id] = ruling  # the fixer may push a corrected PR and report again
            await self.say(f"PR {pr.url} for `{case_id}` failed the safety check: " + "; ".join(problems))
            return
        self.store.save_fix_pr(case_id, pr.url, pr.head_ref, "open", pr.head_sha)
        self.store.set_state(case_id, "FIX_OPEN")
        await self.say(
            f"PR opened for `{case_id}`: {pr.url}. The diff only touches the approved lines. Checked at "
            f"commit `{pr.head_sha[:12]}`; retesting both agents at that commit. If the PR changes after "
            "this, it is no longer the checked fix."
        )
        await self.retest(case_id, pr.head_ref, ruling, pr.head_sha)

    async def retest(self, case_id: str, ref: str, ruling: Ruling, sha: str | None = None) -> dict[str, object]:
        row = self.store.case(case_id)
        if row is None or ruling.truth_value is None:
            raise RuntimeError(f"cannot retest case {case_id}: no case or no approved truth")
        canonical = row["canonical_question_id"]
        texts = [row["question"]] + [q for q in self.index.paraphrases(canonical) if q != row["question"]]
        texts = list(dict.fromkeys(texts))[: self.s.retest_questions]
        qids = {f"q{i + 1}": t for i, t in enumerate(texts)}
        rows: dict[str, dict[str, CaseResult]] = {q: {} for q in qids}
        for label, at in (("before", "main"), ("after", ref)):
            # Each retest question is its own sealed sub-case, linked to the parent in the audit log.
            cases = {q: new_id() for q in qids}
            for q, sub in cases.items():
                self.store.create_case(sub, qids[q], canonical, at)
                self.store.audit(sub, "retest_of", {"parent": case_id, "phase": label})
            pinned = sha if label == "after" else None
            answers = await self.collect(qids, cases, at, pinned)
            engine = self.engine(pinned or at)
            for q, text in qids.items():
                rows[q][label] = engine.evaluate(text, list(answers[q].values()))
        table = [RetestRow(qids[q], rows[q]["before"], rows[q]["after"]) for q in qids]
        summary = retest_summary(table, ruling.truth_value)
        self.store.save_retest(case_id, ref, summary)
        await self.say(retest_card(case_id, ref, table, ruling.truth_value))
        if summary["all_fixed"]:
            self.store.set_state(case_id, "RESOLVED")
        return summary

    # ---- patrol, history ----------------------------------------------------------------------

    async def patrol_holdout(self) -> list[PatrolItem]:
        """Ask the held-out H1 questions on branch holdout/h1 (made by `samepage holdout-branch`).
        H1 is read from disk only here, at run time; nothing is tuned on it."""
        h1 = load_holdout(self.s.holdout_path)
        return await self.patrol(ref="holdout/h1", pairs=[(h1.id, q) for q in h1.questions()])

    async def patrol(
        self, full: bool = False, ref: str = "main", pairs: list[tuple[str, str]] | None = None
    ) -> list[PatrolItem]:
        if pairs is None:
            pairs = [(cid, t) for cid, t in self.index.items] if full else list(self.canonical_text.items())
        pairs = list(dict.fromkeys(pairs))
        await self.say(f"Drift patrol: asking both agents {len(pairs)} question(s) on `{ref}`, sealed.")
        qids = {f"q{i + 1}": text for i, (_, text) in enumerate(pairs)}
        canon = {f"q{i + 1}": cid for i, (cid, _) in enumerate(pairs)}
        cases = {}
        for q, text in qids.items():
            cases[q] = new_id()
            self.store.create_case(cases[q], text, canon[q], ref)
        answers = await self.collect(qids, cases, ref)
        engine = self.engine(ref)
        items = []
        record = []
        for q, text in qids.items():
            result = engine.evaluate(text, list(answers[q].values()))
            self.store.save_result(cases[q], result)
            items.append(PatrolItem(text, result, cases[q] if result.outcome.is_alarm else None))
            record += [
                {
                    "canonical_id": canon[q],
                    "question": text,
                    "ref": ref,
                    "agent": w,
                    "raw": a.raw,
                    "error": a.error,
                    "sealed_at": a.sealed_at,
                    "sha256": a.sha256,
                }
                for w, a in answers[q].items()
            ]
        self._record(record)
        await self.say(patrol_report(items, ref, self.s.switch_agent_name))
        return items

    def _record(self, rows: list[dict[str, Any]]) -> None:
        """Save raw sealed answers so `make eval` can score a real run later."""
        self.s.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.s.reports_dir / f"answers-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def history(self, query: str) -> str:
        if CASE_ID.match(query):
            events = self.store.history(query)
            if not events:
                return f"No history for `{query}`."
            lines = [f"#### History of case `{query}`"]
            lines += [
                f"- {e['at']} **{e['type']}** "
                + ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("type", "at") and v not in (None, ""))
                for e in events
            ]
            return "\n".join(lines)[:15000]
        cid, _ = self.index.best(query)
        rows = self.store.conn.execute(
            "SELECT c.id, c.question, c.state, c.created_at, d.choice, d.decided_by FROM cases c "
            "LEFT JOIN decisions d ON d.case_id = c.id WHERE c.canonical_question_id = ? OR c.question LIKE ? "
            "ORDER BY c.created_at DESC LIMIT 15",
            (cid or "", f"%{query}%"),
        ).fetchall()
        if not rows:
            return f'No cases about "{query}" yet.'
        lines = [f'#### Cases about "{query}"']
        for r in rows:
            ruled = f", {r['choice']} by {r['decided_by']}" if r["choice"] else ""
            lines.append(f"- `{r['id']}` {r['created_at'][:16]} {r['state']}{ruled}: {r['question']}")
        return "\n".join(lines)


async def run(settings: Settings) -> None:
    """Connect to Switch and serve forever."""
    from samepage.switch_client import SwitchClient

    if not (settings.switch_agent_id and settings.switch_agent_api_key and settings.ask_room and settings.desks):
        raise SystemExit(
            "Set SWITCH_AGENT_ID, SWITCH_AGENT_API_KEY, SAMEPAGE_ASK_ROOM and SAMEPAGE_DESKS "
            "(see .env.example and docs/RUNBOOK.md)."
        )
    client = SwitchClient(settings.switch_api_url, settings.switch_agent_id, settings.switch_agent_api_key)
    gh = (
        GitHub(settings.github_token, settings.github_demo_repo)
        if settings.github_token and settings.github_demo_repo
        else None
    )
    arbiter = Arbiter(settings, client, Store(settings.db_path), github=gh)
    rooms = [settings.ask_room, *arbiter.desks.values(), *([settings.fix_room] if settings.fix_room else [])]
    log.info("arbiter listening on %d rooms", len(rooms))
    async for event in client.events(rooms):
        await arbiter.on_event(event)

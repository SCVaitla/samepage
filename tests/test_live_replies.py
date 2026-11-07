"""Replies recorded from the live run on 2026-11-06 (real Claude Code and Codex, real Switch).

These are inputs, not tuned outputs: the test checks the engine reads what the agents
actually wrote. Both agents said Starter has no SSO; the website and sales FAQs say otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path

from samepage.classify import Engine
from samepage.models import Outcome
from samepage.parse import parse_batch
from tests.helpers import corpus

LIVE = Path(__file__).parent / "fixtures" / "live" / "c1-sso-2026-11-06.jsonl"
QUESTION = "Does the Starter plan include single sign-on?"


def test_live_c1_replies_parse_and_agree_on_no() -> None:
    rows = [json.loads(line) for line in LIVE.read_text(encoding="utf-8").splitlines()]
    answers = [parse_batch(r["agent"], r["body"], ["q1"])["q1"] for r in rows]
    assert all(a.error is None for a in answers), [a.error for a in answers]
    engine = Engine(corpus())
    heads = [engine.check(a, QUESTION)[0] for a in answers]
    assert {h.value_key for h in heads} == {"bool:false"}
    result = engine.evaluate(QUESTION, answers)
    # Agents agree, but the website and sales FAQs contradict them: "agree but possibly wrong".
    assert result.outcome is Outcome.SOURCE_CONFLICT
    assert result.proposal is not None and result.proposal.value_key == "bool:false"
    assert {"website/faq.md", "sales/faq.md"} <= {e.path for e in result.proposal.losing}


def test_receipt_for_the_live_case_names_the_consensus_trap(tmp_path: Path) -> None:
    from samepage.receipt import resolution_receipt
    from samepage.store import Store

    rows = [json.loads(line) for line in LIVE.read_text(encoding="utf-8").splitlines()]
    answers = [parse_batch(r["agent"], r["body"], ["q1"])["q1"] for r in rows]
    result = Engine(corpus()).evaluate(QUESTION, answers)
    store = Store(tmp_path / "r.sqlite")
    store.migrate()
    assert "No case" in resolution_receipt(store, "deadbeef")
    store.create_case("db1488ad", QUESTION, "C1")
    store.save_result("db1488ad", result)
    partial = resolution_receipt(store, "db1488ad")
    assert "none recorded yet" in partial and "not run yet" in partial
    store.record_decision("db1488ad", "user", "approve", "bool:false", ["product_spec"], ["website"], "")
    store.save_fix_pr("db1488ad", "https://github.com/o/r/pull/1", "samepage/db1488ad", "open")
    store.save_retest("db1488ad", "samepage/db1488ad", {"questions": 4, "consistent_before": 0, "consistent_after": 4})
    text = resolution_receipt(store, "db1488ad")
    assert "Consensus trap caught" in text
    assert "website/faq.md" in text and "sales/faq.md" in text and "@marketing-lead" in text
    assert "approve by user" in text and "pull/1" in text and "0/4 before → 4/4 after" in text

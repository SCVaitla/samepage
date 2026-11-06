"""Fixer guard and brief, trust ledger, question equivalence."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from samepage.decide import Edit, Ruling
from samepage.equivalence import QuestionIndex, TfidfEmbedder
from samepage.evaluate import equivalence
from samepage.fixer import branch_for, changed_old_lines, diff_problems, fix_brief, pr_body
from samepage.golden import load_golden
from samepage.store import Store
from samepage.trust import ledger, render
from tests.helpers import ROOT, corpus

RULING = Ruling(
    True,
    "ok",
    "days:14",
    "within 14 days",
    "product_spec.md",
    (Edit("support/macros.md", 12, 13, "within 30 days", "30 days"),),
)

DIFF = """diff --git a/support/macros.md b/support/macros.md
--- a/support/macros.md
+++ b/support/macros.md
@@ -11,4 +11,4 @@ Hi [name],
 Thanks for reaching out.
-by our money-back guarantee: refunds are available within 30 days of purchase. I have started
+by our money-back guarantee: refunds are available within 14 days of purchase. I have started
 the refund to your original payment method.
 context
"""


def test_changed_lines_and_guard_accepts_in_span_edit() -> None:
    assert changed_old_lines(DIFF) == {"support/macros.md": {12}}
    assert diff_problems(DIFF, RULING) == []


def test_guard_rejects_other_files_other_lines_and_no_change() -> None:
    other = DIFF.replace("support/macros.md", "website/pricing.md")
    assert any("not approved" in p for p in diff_problems(other, RULING))
    far = DIFF.replace("@@ -11,4 +11,4 @@", "@@ -40,4 +40,4 @@")
    assert any("outside the approved" in p for p in diff_problems(far, RULING))
    assert any("did not change" in p for p in diff_problems("", RULING))


def test_pure_addition_is_attributed_to_the_previous_line() -> None:
    diff = "--- a/x.md\n+++ b/x.md\n@@ -5,2 +5,3 @@\n line five\n+inserted\n line six\n"
    assert changed_old_lines(diff) == {"x.md": {5}}


@given(start=st.integers(1, 500), length=st.integers(1, 5))
def test_guard_is_idempotent(start: int, length: int) -> None:
    ruling = Ruling(True, "ok", "v", "q", "p", (Edit("a.md", start, start + length - 1, "q", "v"),))
    diff = f"--- a/a.md\n+++ b/a.md\n@@ -{start},1 +{start},1 @@\n-old\n+new\n"
    assert diff_problems(diff, ruling) == diff_problems(diff, ruling) == []


def test_branch_brief_and_body() -> None:
    assert branch_for("abcdef12") == "samepage/abcdef12"
    with pytest.raises(ValueError):
        branch_for("../main")
    brief = fix_brief("abcdef12", "Refund window?", RULING, "samepage-fixer")
    assert "support/macros.md` lines 12-13" in brief and "[fix abcdef12] PR:" in brief
    assert "never merges" in pr_body("abcdef12", "Refund window?", RULING, "dev")


def test_trust_ledger_counts_wins_and_losses(tmp_path: Path) -> None:
    s = Store(tmp_path / "t.sqlite")
    assert "No rulings yet" in render(ledger(s))
    for case in ("aaaaaaa1", "aaaaaaa2", "aaaaaaa3"):
        s.create_case(case, "q", "C")
    s.record_decision("aaaaaaa1", "dev", "approve", "days:14", ["product_spec"], ["support_macros"], "r")
    s.record_decision("aaaaaaa2", "dev", "approve", "seats:5", ["product_spec"], ["support_macros", "website"], "r")
    s.record_decision("aaaaaaa3", "dev", "reject", None, [], [], "r")
    rows = ledger(s)
    assert rows[0].source_id == "support_macros" and rows[0].losses == 2 and rows[0].loss_rate == 1.0
    text = render(rows)
    assert "Most often wrong: **support_macros** (2 of 2" in text and ":warning:" in text


def test_equivalence_meets_target_on_golden_paraphrases() -> None:
    golden = load_golden(ROOT / "eval/golden.yaml")
    correct, total, _ = equivalence(golden, corpus().glossary, 0.35)
    assert total == 30
    assert correct / total >= 0.90


def test_index_threshold_and_paraphrase_lookup() -> None:
    idx = QuestionIndex(TfidfEmbedder(corpus().glossary), 0.35)
    assert idx.best("anything") == (None, 0.0)
    idx.add("C2", "How many days do customers have to request a refund?")
    idx.add("C2", "What is the refund window?")
    assert idx.best("refund deadline?")[0] == "C2"
    assert idx.best("Do you have a mobile app?")[0] is None
    assert idx.paraphrases("C2") == [
        "How many days do customers have to request a refund?",
        "What is the refund window?",
    ]


def test_retest_counts_only_clean_outcomes() -> None:
    """Review H6: both agents on the truth is not enough if the docs still disagree."""
    from samepage.classify import Engine
    from samepage.patrol import consistent
    from tests.helpers import answer, claim

    quote = "Single sign-on (SSO) through SAML 2.0 is an Enterprise plan feature"
    a = answer("claude", claim("product_spec.md", quote, "false", "sso", "available", "starter"))
    result = Engine(corpus()).evaluate(
        "Does the Starter plan include single sign-on?", [a, a.model_copy(update={"agent": "codex"})]
    )
    assert result.outcome.value == "SOURCE_CONFLICT"  # website + sales FAQ still say yes
    assert not consistent(result, "bool:false")

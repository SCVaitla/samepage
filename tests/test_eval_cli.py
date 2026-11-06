"""Evaluation harness and CLI. The answers file here is a HAND-WRITTEN fixture to test the
scoring code; it is not a real run and its numbers are never reported."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from samepage.cli import main
from samepage.evaluate import load_answers, report, score
from samepage.golden import Insert, apply_inserts, load_golden
from tests.helpers import ROOT, answer, claim, corpus, unknown


def write_answers(path: Path) -> None:
    golden = {c.id: c for c in load_golden(ROOT / "eval/golden.yaml")}
    sso_a = answer(
        "claude",
        claim("website/faq.md", "Single sign-on is included on all plans", "true", "sso", "available", "starter"),
    )
    sso_b = answer(
        "codex",
        claim(
            "product_spec.md",
            "Single sign-on (SSO) through SAML 2.0 is an Enterprise plan feature",
            "false",
            "sso",
            "available",
            "starter",
        ),
    )
    sup = answer("claude", claim("website/faq.md", "Our support team is available 24/7", "24/7", "support", "hours"))
    rows = []
    for a in (sso_a, sso_b):
        rows.append({"question": golden["C1"].canonical, "agent": a.agent, "raw": a.raw})
    for name in ("claude", "codex"):
        rows.append({"question": golden["C4"].canonical, "agent": name, "raw": sup.raw})
        rows.append({"question": golden["C6"].canonical, "agent": name, "raw": unknown(name).raw})
    rows.append({"question": golden["C2"].canonical, "agent": "claude", "raw": "", "error": "timeout after 240s"})
    rows.append({"question": golden["C2"].canonical, "agent": "codex", "raw": unknown("codex").raw})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_score_counts_detections_from_a_fixture(tmp_path: Path) -> None:
    f = tmp_path / "answers.jsonl"
    write_answers(f)
    from samepage.classify import Engine

    s = score(Engine(corpus()), load_golden(ROOT / "eval/golden.yaml"), load_answers(f))
    assert (s.tp, s.fp, s.fn, s.tn) == (1, 0, 1, 2)  # C1 caught; C2 missed (timeout -> UNSUPPORTED)
    assert s.compatible_total == 1 and s.compatible_alarms == 0
    m = s.metrics()
    assert m["precision"] == 1.0 and m["recall"] == 0.5
    text = report("t", None, s, "fixture")
    assert "| Conflict detection recall | 0.50" in text


def test_report_without_a_run_says_not_run() -> None:
    text = report("t", (29, 30, ["C3: x -> C1 (0.4)"]), None, "none")
    assert "not run (no recorded agent answers)" in text and "29/30" in text and "C3: x" in text


def test_apply_inserts_on_a_copy(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# T\n## A\nold\n")
    apply_inserts(tmp_path, [Insert(path="doc.md", after_heading="## A", text="new line\n")])
    assert (tmp_path / "doc.md").read_text() == "# T\n## A\n\nnew line\nold\n"


def test_cli_check_corpus_and_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("SAMEPAGE_REPORTS_DIR", str(tmp_path / "reports"))
    main(["check-corpus"])
    out = capsys.readouterr().out
    assert "12 source files" in out and "security-and-sso.md:29" in out
    main(["eval"])
    out = capsys.readouterr().out
    assert "not run (no recorded agent answers)" in out and "Question equivalence accuracy" in out
    f = tmp_path / "reports" / "answers-20260101T000000Z.jsonl"
    write_answers(f)
    main(["eval"])
    assert "| Conflict detection precision | 1.00" in capsys.readouterr().out
    assert len(list((tmp_path / "reports").glob("eval-*.md"))) >= 1

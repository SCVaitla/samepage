"""Evaluation: score the engine on REAL recorded agent answers, and question matching on the golden set.

`make eval` runs this. Detection metrics need a recorded run: the arbiter writes
`reports/answers-*.jsonl` every time it patrols (`@samepage-arbiter patrol full`).
Without one, the report says detection was not run. It never fills in numbers.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - read-only `git rev-parse`
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from samepage.classify import Engine
from samepage.corpus import Corpus
from samepage.equivalence import QuestionIndex, TfidfEmbedder
from samepage.golden import GoldenCase, HoldoutCase, apply_inserts
from samepage.models import AgentAnswer, Outcome
from samepage.parse import parse_answer
from samepage.patrol import consistent
from samepage.text import Glossary

TARGETS = {
    "precision": 0.90,
    "recall": 0.80,
    "false_alarm_rate": 0.0,
    "equivalence_accuracy": 0.90,
    "evidence_validity": 1.0,
}


@dataclass
class Scores:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    compatible_total: int = 0
    compatible_alarms: int = 0
    exact: int = 0
    total: int = 0
    claims_verified: int = 0
    claims_total: int = 0
    consistent: int = 0
    consistency_total: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    def ratio(self, num: int, den: int) -> float | None:
        return num / den if den else None

    def metrics(self) -> dict[str, float | None]:
        return {
            "precision": self.ratio(self.tp, self.tp + self.fp),
            "recall": self.ratio(self.tp, self.tp + self.fn),
            "false_alarm_rate": self.ratio(self.compatible_alarms, self.compatible_total),
            "state_accuracy": self.ratio(self.exact, self.total),
            "evidence_validity": self.ratio(self.claims_verified, self.claims_total),
            "consistency_before": self.ratio(self.consistent, self.consistency_total),
        }


def equivalence(golden: list[GoldenCase], glossary: Glossary, threshold: float) -> tuple[int, int, list[str]]:
    """Map each paraphrase onto the canonical questions only; count the right ones."""
    index = QuestionIndex(TfidfEmbedder(glossary), threshold)
    for case in golden:
        index.add(case.id, case.canonical)
    correct, total, misses = 0, 0, []
    for case in golden:
        for p in case.paraphrases:
            got, score = index.best(p)
            total += 1
            if got == case.id:
                correct += 1
            else:
                misses.append(f"{case.id}: {p!r} -> {got} ({score:.2f})")
    return correct, total, misses


def load_answers(path: Path) -> dict[str, list[AgentAnswer]]:
    by_question: dict[str, list[AgentAnswer]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        # Each record holds one question's block (the arbiter splits batch replies before recording).
        if r.get("error"):
            ans = AgentAnswer(agent=r["agent"], raw=r.get("raw", ""), error=r["error"])
        else:
            ans = parse_answer(r["agent"], r["raw"], r.get("sealed_at", ""))
        by_question[r["question"]].append(ans)
    return by_question


def score(engine: Engine, cases: list[GoldenCase], answers: dict[str, list[AgentAnswer]]) -> Scores:
    s = Scores()
    for case in cases:
        for q in case.questions():
            if q not in answers:
                continue
            result = engine.evaluate(q, answers[q])
            expected_alarm = case.expected.is_alarm
            got_alarm = result.outcome.is_alarm
            s.total += 1
            s.exact += result.outcome == case.expected
            s.tp += expected_alarm and got_alarm
            s.fp += (not expected_alarm) and got_alarm
            s.fn += expected_alarm and not got_alarm
            s.tn += (not expected_alarm) and not got_alarm
            if case.expected is Outcome.COMPATIBLE:
                s.compatible_total += 1
                s.compatible_alarms += got_alarm
            v, t = result.evidence_validity()
            s.claims_verified += v
            s.claims_total += t
            if case.truth:
                s.consistency_total += 1
                s.consistent += consistent(result, case.truth)
            s.rows.append(
                {
                    "case": case.id,
                    "question": q,
                    "expected": case.expected.value,
                    "got": result.outcome.value,
                    "why": result.reasons[-1] if result.reasons else "",
                }
            )
    return s


def holdout_engine(corpus_dir: Path, holdout: HoldoutCase) -> Engine:
    """An engine over a temporary copy of the corpus with the held-out text inserted."""
    tmp = Path(tempfile.mkdtemp(prefix="samepage-holdout-"))
    shutil.copytree(corpus_dir, tmp / "corpus")
    apply_inserts(tmp / "corpus", holdout.inserts)
    return Engine(Corpus.from_dir(tmp / "corpus"))


def commit_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,  # nosec B603 B607
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _fmt(value: float | None) -> str:
    return "not run" if value is None else f"{value:.2f}"


def report(title: str, eq: tuple[int, int, list[str]] | None, scores: Scores | None, source: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {title}",
        "",
        f"- Date: {stamp}",
        f"- Commit: `{commit_hash()}`",
        f"- Agent answers: {source}",
        "",
    ]
    lines += ["| Metric | Result | Target |", "|---|---|---|"]
    if eq is not None:
        c, t, _ = eq
        lines.append(f"| Question equivalence accuracy | {c}/{t} = {c / t:.2f} | ≥ {TARGETS['equivalence_accuracy']} |")
    if scores is None:
        lines += [
            "| Conflict detection precision / recall | not run (no recorded agent answers) | ≥ 0.90 / ≥ 0.80 |",
            "| False alarms on COMPATIBLE | not run | 0 |",
            "| Evidence validity | not run | 100% |",
        ]
    else:
        m = scores.metrics()
        lines += [
            f"| Conflict detection precision | {_fmt(m['precision'])} (TP {scores.tp}, FP {scores.fp}) | ≥ 0.90 |",
            f"| Conflict detection recall | {_fmt(m['recall'])} (FN {scores.fn}) | ≥ 0.80 |",
            f"| False alarm rate on COMPATIBLE | {_fmt(m['false_alarm_rate'])} "
            f"({scores.compatible_alarms}/{scores.compatible_total}) | 0 |",
            f"| Exact state accuracy | {_fmt(m['state_accuracy'])} ({scores.exact}/{scores.total}) | n/a |",
            f"| Evidence validity (claims with verified quotes) | {_fmt(m['evidence_validity'])} "
            f"({scores.claims_verified}/{scores.claims_total}) | 1.00 of displayed claims |",
            f"| Both agents right and consistent (before fix) | {_fmt(m['consistency_before'])} "
            f"({scores.consistent}/{scores.consistency_total}) | n/a (after-fix comes from retest) |",
        ]
    if eq is not None and eq[2]:
        lines += ["", "## Question matching misses", *[f"- {m}" for m in eq[2]]]
    if scores is not None and scores.rows:
        lines += [
            "",
            "## Per question",
            "| Case | Question | Expected | Got | Why |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {r['case']} | {r['question']} | {r['expected']} | {r['got']} | {r['why'][:160]} |" for r in scores.rows
        ]
    lines += [
        "",
        "Numbers are computed from the files named above. Expected states are never edited to pass.",
    ]
    return "\n".join(lines) + "\n"

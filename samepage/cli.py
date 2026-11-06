"""Command line: `samepage <command>`. Run `samepage -h` for the list."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from samepage.config import Settings


def cmd_serve(args: argparse.Namespace, s: Settings) -> None:
    import uvicorn

    from samepage.api import create_app

    uvicorn.run(create_app(s), host=args.host, port=args.port)


def cmd_arbiter(_: argparse.Namespace, s: Settings) -> None:
    from samepage.arbiter import run

    asyncio.run(run(s))


def cmd_check_corpus(_: argparse.Namespace, s: Settings) -> None:
    from samepage.corpus import Corpus

    c = Corpus.from_dir(s.corpus_dir)
    print(f"{len(c.files)} source files, {len(c.passages)} passages, {len(c.injections)} suspicious line(s)")
    for fam in c.families:
        files = [p for p in c.files if c.family_of(p) == fam]
        print(f"  {fam.id:15} authority {fam.authority}  owner {fam.owner:16} {len(files)} file(s)")
    for i in c.injections:
        print(f"  ignored (reads like an instruction to AI): {i.path}:{i.line}: {i.text}")


def cmd_eval(args: argparse.Namespace, s: Settings) -> None:
    from samepage.classify import Engine
    from samepage.corpus import Corpus
    from samepage.evaluate import equivalence, holdout_engine, load_answers, report, score
    from samepage.golden import GoldenCase, load_golden, load_holdout

    corpus = Corpus.from_dir(s.corpus_dir)
    answers_file = Path(args.answers) if args.answers else _latest(s.reports_dir)
    if args.holdout:
        h1 = load_holdout(Path(args.holdout_file))
        cases: list[GoldenCase] = [h1]
        engine = holdout_engine(s.corpus_dir, h1)
        title, eq = "SamePage held-out evaluation (H1)", None
    else:
        cases = load_golden(s.golden_path)
        engine = Engine(corpus, s.quote_slack_lines, s.min_anchor_terms)
        title = "SamePage evaluation (golden set C1-C6)"
        eq = equivalence(cases, corpus.glossary, s.equivalence_threshold)
    scores = None
    source = "none recorded yet: run `@samepage-arbiter patrol full` in the room first"
    if answers_file is not None:
        answers = load_answers(answers_file)
        if any(q in answers for c in cases for q in c.questions()):
            scores = score(engine, cases, answers)
            source = f"`{answers_file}`"
    text = report(title, eq, scores, source)
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    from datetime import UTC, datetime

    name = ("eval-holdout-" if args.holdout else "eval-") + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".md"
    (s.reports_dir / name).write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved {s.reports_dir / name}")


def _latest(reports: Path) -> Path | None:
    files = sorted(reports.glob("answers-*.jsonl")) if reports.exists() else []
    return files[-1] if files else None


def cmd_holdout_branch(args: argparse.Namespace, _: Settings) -> None:
    """Create branch holdout/h1 in a local clone of the docs repo, with H1's text inserted."""
    import subprocess  # nosec B404

    from samepage.golden import apply_inserts, load_holdout

    repo = Path(args.repo)
    h1 = load_holdout(Path(args.holdout_file))

    def git(*a: str) -> None:
        subprocess.run(["git", "-C", str(repo), *a], check=True, timeout=60)  # nosec B603 B607

    git("checkout", "-B", "holdout/h1", "origin/main")
    apply_inserts(repo / args.subdir if args.subdir else repo, h1.inserts)
    git("commit", "-am", "eval: insert held-out case H1 (not for merging)")
    print("Created holdout/h1. Push it with: git -C", repo, "push -u origin holdout/h1")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
    parser = argparse.ArgumentParser(prog="samepage", description=__doc__)
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("serve", help="run the HTTP API (/healthz, /v1/evaluate)")
    p.add_argument("--host", default="0.0.0.0")  # nosec B104 - inside the container
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("arbiter", help="join Switch as the SamePage Arbiter").set_defaults(fn=cmd_arbiter)
    sub.add_parser("check-corpus", help="list sources, passages and ignored lines").set_defaults(fn=cmd_check_corpus)
    p = sub.add_parser("eval", help="score recorded agent answers and question matching")
    p.add_argument("--answers", help="answers-*.jsonl file (default: latest in reports/)")
    p.add_argument("--holdout", action="store_true", help="score the held-out case H1")
    p.add_argument("--holdout-file", default="eval/holdout/h1.yaml")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("holdout-branch", help="make branch holdout/h1 in a local docs clone")
    p.add_argument("--repo", required=True)
    p.add_argument("--subdir", default="")
    p.add_argument("--holdout-file", default="eval/holdout/h1.yaml")
    p.set_defaults(fn=cmd_holdout_branch)
    args = parser.parse_args(argv)
    args.fn(args, Settings())


if __name__ == "__main__":
    main(sys.argv[1:])

"""Load the golden evaluation set (eval/golden.yaml) and, separately, the held-out case."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from samepage.models import Outcome


class GoldenCase(BaseModel):
    id: str
    topic: str
    expected: Outcome
    truth: str | None = None
    canonical: str
    paraphrases: list[str]

    def questions(self) -> list[str]:
        return [self.canonical, *self.paraphrases]


class Insert(BaseModel):
    path: str
    after_heading: str
    text: str


class HoldoutCase(GoldenCase):
    inserts: list[Insert]


def load_golden(path: Path) -> list[GoldenCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(c) for c in data["cases"]]


def load_holdout(path: Path) -> HoldoutCase:
    return HoldoutCase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def apply_inserts(corpus_dir: Path, inserts: list[Insert]) -> None:
    """Insert held-out text after a heading, in a COPY of the corpus (never the original)."""
    for ins in inserts:
        target = corpus_dir / ins.path
        lines = target.read_text(encoding="utf-8").splitlines()
        at = lines.index(ins.after_heading) + 1
        block = ["", *ins.text.rstrip("\n").splitlines()]
        target.write_text("\n".join(lines[:at] + block + lines[at:]) + "\n", encoding="utf-8")

"""Ingest: load the docs corpus with stable line numbers, authority and owner per source.

A corpus can be read from a plain directory or from a git ref (for retests against a
fix branch). Line numbers are the file's own line numbers, 1-based, so they match
what an agent sees when it opens the file.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import subprocess  # nosec B404 - only used to run git with fixed argument lists
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from samepage.injection import looks_like_injection
from samepage.models import Injection, Passage
from samepage.text import Glossary

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


@dataclass(frozen=True)
class SourceFamily:
    id: str
    title: str
    patterns: tuple[str, ...]
    authority: int
    owner: str
    surface: str


@dataclass
class Corpus:
    files: dict[str, list[str]]  # path -> lines (no trailing newline)
    families: list[SourceFamily]
    glossary: Glossary
    plans: list[str] = field(default_factory=list)
    sha256: dict[str, str] = field(default_factory=dict)
    passages: list[Passage] = field(default_factory=list)
    injections: list[Injection] = field(default_factory=list)

    # ---- loading ---------------------------------------------------------------

    @classmethod
    def from_dir(cls, root: Path) -> Corpus:
        texts = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}
        return cls._build(
            texts, (root / "sources.yaml").read_text(encoding="utf-8"), Glossary.load(root / "glossary.yaml")
        )

    @classmethod
    def from_git(cls, repo: Path, ref: str, subdir: str = "") -> Corpus:
        """Read the corpus as it is at `ref` (a branch, tag or sha) without checking it out."""
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", ref) or ".." in ref:
            raise ValueError(f"unsafe git ref: {ref!r}")
        prefix = f"{subdir.strip('/')}/" if subdir else ""

        def git(*args: str) -> str:
            result = subprocess.run(  # nosec B603 B607 - fixed git subcommands, validated ref
                ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, timeout=30
            )
            return result.stdout

        names = [n for n in git("ls-tree", "-r", "--name-only", ref).splitlines() if n.startswith(prefix)]
        texts = {n[len(prefix) :]: git("show", f"{ref}:{n}") for n in names if n.endswith(".md")}
        sources = git("show", f"{ref}:{prefix}sources.yaml")
        glossary_name = f"{prefix}glossary.yaml"
        groups = yaml.safe_load(git("show", f"{ref}:{glossary_name}")) if glossary_name in names else {}
        return cls._build(texts, sources, Glossary({k: list(v) for k, v in (groups or {}).get("groups", {}).items()}))

    @classmethod
    def _build(cls, texts: dict[str, str], sources_yaml: str, glossary: Glossary) -> Corpus:
        spec = yaml.safe_load(sources_yaml) or {}
        families = [
            SourceFamily(
                id=str(s["id"]),
                title=str(s.get("title", s["id"])),
                patterns=tuple(s["paths"]),
                authority=int(s["authority"]),
                owner=str(s.get("owner", "")),
                surface=str(s.get("surface", "")),
            )
            for s in spec.get("sources", [])
        ]
        corpus = cls(
            files={},
            families=families,
            glossary=glossary,
            plans=[str(p).lower() for p in spec.get("plans", [])],
        )
        for path, text in texts.items():
            if corpus.family_of(path) is None:
                continue  # not a declared source (README etc.)
            corpus.files[path] = text.splitlines()
            corpus.sha256[path] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        corpus._index()
        return corpus

    # ---- lookups ---------------------------------------------------------------

    def family_of(self, path: str) -> SourceFamily | None:
        for fam in self.families:
            if any(fnmatch.fnmatch(path, pat) for pat in fam.patterns):
                return fam
        return None

    def normalize_path(self, path: str) -> str | None:
        """Accept 'corpus/x.md', './x.md' or 'x.md'; return the corpus-relative path if known."""
        cleaned = path.strip().lstrip("./")
        for candidate in (cleaned, cleaned.removeprefix("corpus/")):
            if candidate in self.files:
                return candidate
        return None

    # ---- passages ----------------------------------------------------------------

    def _index(self) -> None:
        """Split each file into blocks (runs of non-blank lines) under their nearest heading."""
        for path, lines in self.files.items():
            fam = self.family_of(path)
            if fam is None:  # cannot happen: files only holds declared sources
                raise ValueError(f"{path} is not a declared source")
            heading = ""
            blocks: list[tuple[str, list[tuple[int, str]]]] = [("", [])]
            for number, line in enumerate(lines, start=1):
                if looks_like_injection(line):
                    self.injections.append(Injection(path=path, line=number, text=line.strip()))
                    continue  # never part of a fact
                match = HEADING.match(line)
                if match:
                    heading = match.group(2).strip()
                    blocks.append((heading, []))
                elif not line.strip() or line.lstrip().startswith("<!--"):
                    blocks.append((heading, []))
                else:
                    blocks[-1][1].append((number, line))
            for block_heading, block in blocks:
                if block:
                    self.passages.extend(self._passages_for(path, fam, block_heading, block))

    def _passages_for(self, path: str, fam: SourceFamily, heading: str, block: list[tuple[int, str]]) -> list[Passage]:
        rows = [(n, ln) for n, ln in block if TABLE_ROW.match(ln)]
        if rows and len(rows) == len(block):
            return self._table_passages(path, fam, heading, rows)
        return [
            Passage(
                path=path,
                source_id=fam.id,
                authority=fam.authority,
                line_start=block[0][0],
                line_end=block[-1][0],
                heading=heading,
                text=" ".join(ln.strip() for _, ln in block),
            )
        ]

    def _table_passages(self, path: str, fam: SourceFamily, heading: str, rows: list[tuple[int, str]]) -> list[Passage]:
        """One passage per table row, written out as 'Column: cell row-label', so a
        row like '| Seats per workspace | 5 | 250 |' under a 'Starter | Pro' header
        reads 'Starter: 5 Seats per workspace; Pro: 250 Seats per workspace'."""

        def cells(line: str) -> list[str]:
            return [c.strip() for c in line.strip().strip("|").split("|")]

        header = cells(rows[0][1])
        out: list[Passage] = []
        for number, line in rows[1:]:
            if TABLE_RULE.match(line):
                continue
            values = cells(line)
            label = values[0] if values else ""
            parts = [f"{col}: {val} {label}" for col, val in zip(header[1:], values[1:], strict=False)]
            out.append(
                Passage(
                    path=path,
                    source_id=fam.id,
                    authority=fam.authority,
                    line_start=number,
                    line_end=number,
                    heading=heading,
                    text=f"{label}. " + "; ".join(parts) + ".",
                )
            )
        return out

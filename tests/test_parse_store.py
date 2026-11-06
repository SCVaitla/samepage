"""Parsing agent replies, and the SQLite store (append-only audit, first answer sealed once)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from samepage.parse import parse_answer, parse_batch, timed_out
from samepage.store import Store
from tests.helpers import answer, claim

GOOD = '```json\n{"question_id": "q1", "answer": "Five", "claims": [], "unknown": true}\n```'


def test_parse_good_bad_and_violations() -> None:
    assert parse_answer("a", GOOD).contract is not None
    assert parse_answer("a", "sure! it's 5").error.startswith("invalid_json")  # type: ignore[union-attr]
    assert parse_answer("a", "[1]").error == "invalid_json: expected an object"
    bad = '```json\n{"claims": [{"entity": "x"}]}\n```'
    assert parse_answer("a", bad).error.startswith("contract_violation")  # type: ignore[union-attr]
    assert "larger than" in (parse_answer("a", "x" * 100, max_bytes=10).error or "")
    assert timed_out("a", 90).error == "timeout after 90s"


def test_parse_batch_maps_blocks_and_flags_missing() -> None:
    raw = "[batch 1] " + GOOD + '\n```json\n{"question_id": "q2", "answer": "No", "unknown": true}\n```'
    got = parse_batch("a", raw, ["q1", "q2", "q3"])
    assert got["q1"].contract and got["q2"].contract
    assert got["q3"].error == "no valid answer block for q3"
    unlabeled = '```json\n{"answer": "x", "unknown": true}\n```\n```json\n{"answer": "y", "unknown": true}\n```'
    got = parse_batch("a", unlabeled, ["q1", "q2"])
    assert got["q2"].contract.answer == "y"  # type: ignore[union-attr]
    assert parse_batch("a", "x" * 100, ["q1"], max_bytes=10)["q1"].error


def test_store_seals_first_answer_only_and_audit_is_append_only(tmp_path: Path) -> None:
    s = Store(tmp_path / "t.sqlite")
    s.create_case("abcdef12", "q?", "C1")
    a = answer("claude", claim("product_spec.md", "Starter workspaces are limited to 5 seats", "5"))
    a = a.model_copy(update={"sha256": "h1"})
    assert s.seal_answer("abcdef12", a)
    assert not s.seal_answer("abcdef12", a.model_copy(update={"raw": "changed"}))
    types = [e["type"] for e in s.history("abcdef12")]
    assert types == ["case_opened", "answer_sealed"]
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        s.conn.execute("UPDATE audit_events SET type = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        s.conn.execute("DELETE FROM audit_events")
    assert s.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_store_migrations_are_idempotent(tmp_path: Path) -> None:
    Store(tmp_path / "t.sqlite")
    s = Store(tmp_path / "t.sqlite")
    assert s.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    assert s.result("nope") is None and s.case("nope") is None
    s.add_question("q1", "text", "C1")
    s.add_question("q1", "text", "C1")
    assert len(s.questions()) == 1

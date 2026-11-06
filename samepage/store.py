"""SQLite storage (WAL mode) with numbered SQL migrations and an append-only audit log.

Plain sqlite3, no ORM: every query is visible here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from samepage.models import AgentAnswer, CaseResult

MIGRATIONS = Path(__file__).parent / "migrations"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: Path | str) -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for script in sorted(MIGRATIONS.glob("*.sql")):
            version = int(script.name.split("_", 1)[0])
            if version > current:
                self.conn.executescript(script.read_text(encoding="utf-8"))
                self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        self.conn.commit()

    # ---- audit -----------------------------------------------------------------

    def audit(self, case_id: str | None, type_: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO audit_events (case_id, type, payload_json, at) VALUES (?, ?, ?, ?)",
            (case_id, type_, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_iso()),
        )
        self.conn.commit()

    def history(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT type, payload_json, at FROM audit_events WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
        return [{"type": r["type"], "at": r["at"], **json.loads(r["payload_json"])} for r in rows]

    # ---- cases -------------------------------------------------------------------

    def create_case(self, case_id: str, question: str, canonical_id: str, ref: str = "main") -> None:
        self.conn.execute(
            "INSERT INTO cases (id, canonical_question_id, question, state, ref, created_at) "
            "VALUES (?, ?, ?, 'OPEN', ?, ?)",
            (case_id, canonical_id, question, ref, now_iso()),
        )
        self.conn.commit()
        self.audit(case_id, "case_opened", {"question": question, "canonical_id": canonical_id, "ref": ref})

    def seal_answer(self, case_id: str, answer: AgentAnswer) -> bool:
        """Record an agent's first answer. Returns False if this agent already answered."""
        try:
            self.conn.execute(
                "INSERT INTO answers (case_id, agent, raw, parsed_ok, sealed_at, sha256) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    answer.agent,
                    answer.raw,
                    int(answer.contract is not None),
                    answer.sealed_at or now_iso(),
                    answer.sha256,
                ),
            )
        except sqlite3.IntegrityError:
            return False
        self.conn.commit()
        self.audit(
            case_id,
            "answer_sealed",
            {
                "agent": answer.agent,
                "sha256": answer.sha256,
                "parsed_ok": answer.contract is not None,
                "error": answer.error,
            },
        )
        return True

    def save_result(self, case_id: str, result: CaseResult) -> None:
        self.conn.execute(
            "UPDATE cases SET state = ?, result_json = ? WHERE id = ?",
            (result.outcome.value, result.model_dump_json(), case_id),
        )
        self.conn.commit()
        self.audit(case_id, "classified", {"outcome": result.outcome.value, "reasons": result.reasons})

    def set_state(self, case_id: str, state: str) -> None:
        self.conn.execute("UPDATE cases SET state = ? WHERE id = ?", (state, case_id))
        self.conn.commit()
        self.audit(case_id, "state_changed", {"state": state})

    def case(self, case_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return row

    def result(self, case_id: str) -> CaseResult | None:
        row = self.case(case_id)
        if row is None or row["result_json"] is None:
            return None
        return CaseResult.model_validate_json(row["result_json"])

    # ---- decisions -----------------------------------------------------------------

    def record_decision(
        self,
        case_id: str,
        decided_by: str,
        choice: str,
        truth_value: str | None,
        winners: list[str],
        losers: list[str],
        rationale: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO decisions (case_id, decided_by, choice, truth_value, winners_json, losers_json, "
            "rationale, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                decided_by,
                choice,
                truth_value,
                json.dumps(sorted(set(winners))),
                json.dumps(sorted(set(losers))),
                rationale,
                now_iso(),
            ),
        )
        self.conn.commit()
        self.audit(
            case_id,
            "decision",
            {
                "by": decided_by,
                "choice": choice,
                "truth": truth_value,
                "winners": sorted(set(winners)),
                "losers": sorted(set(losers)),
                "rationale": rationale,
            },
        )

    def decisions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM decisions ORDER BY id").fetchall())

    def decision_for(self, case_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,)
        ).fetchone()
        return row

    # ---- fixes and retests ------------------------------------------------------------

    def fix_pr(self, case_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute("SELECT * FROM fix_prs WHERE case_id = ?", (case_id,)).fetchone()
        return row

    def save_fix_pr(self, case_id: str, url: str, branch: str, status: str, head_sha: str = "") -> None:
        self.conn.execute(
            "INSERT INTO fix_prs (case_id, url, branch, status, head_sha) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(case_id) DO UPDATE SET url = excluded.url, status = excluded.status, "
            "head_sha = excluded.head_sha",
            (case_id, url, branch, status, head_sha),
        )
        self.conn.commit()
        self.audit(case_id, "fix_pr", {"url": url, "branch": branch, "status": status, "head_sha": head_sha})

    def save_retest(self, case_id: str, ref: str, results: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO retest_runs (case_id, ref, results_json, at) VALUES (?, ?, ?, ?)",
            (case_id, ref, json.dumps(results, sort_keys=True), now_iso()),
        )
        self.conn.commit()
        self.audit(case_id, "retest", {"ref": ref, **results})

    # ---- questions ---------------------------------------------------------------------

    def add_question(self, question_id: str, text: str, canonical_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO questions (id, text, canonical_id, created_at) VALUES (?, ?, ?, ?)",
            (question_id, text, canonical_id, now_iso()),
        )
        self.conn.commit()

    def questions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM questions ORDER BY created_at").fetchall())

-- SamePage schema, version 1. Applied once by samepage.store.Store.migrate().

CREATE TABLE IF NOT EXISTS questions (
    id            TEXT PRIMARY KEY,
    text          TEXT NOT NULL,
    canonical_id  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id                     TEXT PRIMARY KEY,
    canonical_question_id  TEXT NOT NULL,
    question               TEXT NOT NULL,
    state                  TEXT NOT NULL,
    ref                    TEXT NOT NULL DEFAULT 'main',
    result_json            TEXT,
    created_at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL REFERENCES cases(id),
    agent      TEXT NOT NULL,
    raw        TEXT NOT NULL,
    parsed_ok  INTEGER NOT NULL,
    sealed_at  TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    UNIQUE (case_id, agent)          -- only the first answer per agent is sealed
);

CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT NOT NULL REFERENCES cases(id),
    decided_by    TEXT NOT NULL,
    choice        TEXT NOT NULL CHECK (choice IN ('approve', 'override', 'reject')),
    truth_value   TEXT,
    winners_json  TEXT NOT NULL,      -- source ids judged right
    losers_json   TEXT NOT NULL,      -- source ids judged wrong
    rationale     TEXT NOT NULL,
    decided_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fix_prs (
    case_id  TEXT PRIMARY KEY REFERENCES cases(id),   -- one PR per case (idempotent)
    url      TEXT NOT NULL,
    branch   TEXT NOT NULL,
    status   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retest_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT NOT NULL REFERENCES cases(id),
    ref           TEXT NOT NULL,
    results_json  TEXT NOT NULL,
    at            TEXT NOT NULL
);

-- Append-only audit log: the triggers refuse every UPDATE and DELETE.
CREATE TABLE IF NOT EXISTS audit_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT,
    type          TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    at            TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

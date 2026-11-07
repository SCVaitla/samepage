# Changelog


## 2026-11-06 / 07: live run

### Added
- `samepage connect` and `samepage wire-rooms`: one-command setup against Switch Console's local server.
- Resolution receipt (posted when a case resolves; `receipt <case>`), and the "consensus trap" label on SOURCE_CONFLICT cards.
- Commands in samepage-ask work without the @mention; one log line and a raw frame (`reports/frames.jsonl`) per Switch message.
- Real evaluation runs: `reports/eval-20261106T220548Z.md` (golden) and `reports/eval-holdout-20261106T220951Z.md` (H1), with the recorded answers.

### Fixed (found by real agent answers)
- A quote wrapped across lines was read as two clauses, and "not available (Enterprise only)" was read as yes. The real replies are now a test (`tests/test_live_replies.py`).
- Retest sub-cases stayed OPEN; the ask room got a Switch warning when SamePage mentioned the fixer.

### Changed
- The fixer opens PRs with the local `gh` sign-in: Console's GitHub connector needs an https server address.

## 0.1.0 (unreleased, 2026-11-05)

### Added
- Fictional Juniper Desk corpus (12 docs) with planted drift C1–C7, golden set (6 cases × 6 questions), held-out H1.
- Deterministic engine: verbatim evidence checks, value normalization, corpus scan, ordered outcome rules, proposals.
- Investigation card with **blast radius** and **owner routing**.
- Rulings (approve / override / reject) with authority checked in code; append-only audit log.
- **Drift patrol** (`patrol`, `patrol full`, `patrol on <ref>`, `patrol holdout`) and **source trust ledger** (`trust`).
- Fixer brief, PR body and diff guard; retest before/after on the fix branch.
- Switch agent-protocol client and arbiter with batch sealed collection; Switch template (3 agents, 5 rooms).
- Eval harness that scores only recorded runs; CLI (`register`, `rooms`, `arbiter`, `eval`, `check-corpus`, `holdout-branch`).
- Tooling: uv lockfile, ruff, mypy --strict, pytest + hypothesis, bandit, pip-audit, gitleaks, pre-commit, CI, Docker.

### Fixed (independent QA/Security review, see docs/REVIEW.md)
- A real but irrelevant quote, or a quote stating a different value, could produce VERIFIED.
- Agreement that couldn't be cross-checked was reported VERIFIED; it is now UNSUPPORTED.
- Which docs got scanned depended on one agent's naming; topic words now come from the question and all claims.
- Stale, untagged or foreign desk replies could be sealed to the wrong case.
- The diff guard missed renames, mode changes, new/deleted/binary files, header-looking lines and big insertions.
- RESOLVED could be set while the docs still conflicted.
- Owners of losing docs could override in their own favour; PR base and head commit were not pinned.
- Normalizer: negation after the plan name, number words like "forty-five", "12 months" vs "one year".
- The glossary matched inside its own tokens.

### Changed
- Room commands are @mentions (`@samepage-arbiter approve <case>`), not slash commands: Switch does not forward custom slash commands to agents (ADR 0001).

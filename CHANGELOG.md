# Changelog

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

### Changed
- Room commands are @mentions (`@samepage-arbiter approve <case>`), not slash commands: Switch does not forward custom slash commands to agents (ADR 0001).

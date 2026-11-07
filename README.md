# SamePage

**SamePage turns disagreements between AI agents into an investigation, a human decision, and a verified fix.**

Companies keep the same product facts in many places: the spec, the website, the help center, the sales FAQ, support macros. Those copies drift apart. AI agents answering from them give inconsistent answers, and nobody notices until a customer does. SamePage asks **two different agents** the same question **without letting them see each other's answer**. When they disagree, or agree while the docs don't, it shows the evidence, asks the owners to rule, opens a pull request, and proves the fix with a retest.

Built for Flip the Switch (Best Business Workflow). *Juniper Desk, the company in every example, is fictional.*

> **Status (2026-11-06):** runs live on Switch Console 0.40.1 (server 0.31.0) with real Claude Code and Codex agents and a real GitHub repo. The full loop ran end to end: ask → sealed answers → card → `approve` → fixer opened [PR #1](https://github.com/SCVaitla/juniper-desk-docs/pull/1) → retest 0/4 → 4/4 → RESOLVED. Evaluation numbers below come from real agent answers.

## How Switch is used

Switch is the backbone, not a plugin. Without it there are no sealed rooms, no agents to compare, and nowhere for the human to rule.

| Piece | Switch feature | Where |
|---|---|---|
| **The SamePage Arbiter is itself a Switch agent** | Agent protocol: register once, SSE stream in, HTTP posts out, 2 s heartbeat | `samepage/switch_client.py`, `samepage/arbiter.py` |
| **Sealed answers** | Each worker gets a *private desk room*; Switch only lets an agent read rooms it is a member of | `switch/samepage.template.yaml`, ADR 0001 |
| **Two different agents** | Claude Code and Codex, run by Switch Console, each with the docs repo cloned through `repo:` | template `agents:` |
| **Human ruling in the chat** | A reply in the ask room (`approve <case>`), received as a message event with the sender's identity | `samepage/decide.py` |
| **The fix** | A Claude Code fixer agent in its own private room, opening the PR with `gh` | template, `samepage/fixer.py` |
| **One-click setup** | A Switch YAML template: 3 agents, 5 rooms, links | `switch/samepage.template.yaml` |

```mermaid
sequenceDiagram
  actor H as Teammate / owner
  participant Ask as samepage-ask (room)
  participant Arb as SamePage Arbiter (Switch agent)
  participant DA as desk-claude (private)
  participant DB as desk-codex (private)
  participant Fix as samepage-fix (private)
  H->>Ask: ask Does Starter include SSO?
  Ask-->>Arb: SSE message event
  par sealed
    Arb->>DA: @samepage-claude [batch] q1
    Arb->>DB: @samepage-codex [batch] q1
  end
  DA-->>Arb: JSON claims + verbatim quotes (sealed: sha256 + time)
  DB-->>Arb: JSON claims + verbatim quotes (sealed: sha256 + time)
  Arb->>Ask: Card: both answers revealed, evidence, blast radius, owners
  H->>Ask: approve <case>
  Arb->>Fix: Fix brief (exact lines)
  Fix-->>Arb: [fix case] PR: url
  Arb->>Arb: Diff guard (only approved lines), then retest on the branch
  Arb->>Ask: Retest card: 0/4 before → 4/4 after · RESOLVED
```

## What it looks like

From the live run on 2026-11-06 (real Switch, Claude Code, Codex and GitHub):

| Both agents in one room (Gate 0) | The investigation card |
|---|---|
| ![smoke room](docs/evidence/gate0-smoke-both-workers.png) | ![card](docs/evidence/live-c1-first-card-before-fix.png) |
| **The fixer opens a real PR** | **Retest on the fix branch: RESOLVED** |
| ![fixer](docs/evidence/live-c1-fixer-opened-pr.png) | ![retest](docs/evidence/live-c1-retest-resolved.png) |

The card screenshot is from the first live ask, before two reading bugs were fixed (it says CONFLICT; the same question now says SOURCE_CONFLICT, as in the retest). The fix and its test, built from the agents' real replies, are in `tests/test_live_replies.py`.

## Features

- **Sealed second opinion:** two agents answer separately; the audit log proves the order.
- **Evidence or it didn't happen:** every quote is checked word for word at the cited lines; the quoted passage must be about the question, and the quote itself must state the value claimed.
- **Consensus trap:** two agents agreeing doesn't mean the company's knowledge is right. The engine scans the docs for every passage about the same fact (found by the question's and both agents' topic words), so two agents agreeing on a stale fact still raise `SOURCE_CONFLICT`. Agreement it cannot cross-check is `UNSUPPORTED`, never `VERIFIED`.
- **Blast radius:** every place the wrong fact appears, and which team reads it.
- **Owner routing:** the owners of the wrong docs are @mentioned and may approve the proposed fix (overrides and rejects need an approver).
- **Drift patrol:** `patrol` re-asks everything known, before a customer does.
- **Source trust ledger:** `trust` shows which docs keep losing rulings.
- **Resolution receipt:** when a case resolves, one card sums it up from the audit records: both answers, the wrong docs and their owners, who ruled, the PR, and the retest (0/4 → 4/4). `receipt <case>` shows it again.
- **Safe fix:** a PR that changes anything beyond the approved lines is refused, and the checked commit is what gets retested; nothing is ever auto-merged.

## Quickstart

```sh
make setup      # locked deps, git hooks, .env
make check      # lint, mypy --strict, tests with coverage, bandit, pip-audit
make seed       # what the engine sees in the docs
make up         # engine API in Docker: http://localhost:8080/healthz
```

The live demo (Switch Console, the two agents, the docs repo) is set up step by step in **[docs/RUNBOOK.md](docs/RUNBOOK.md)**. In short: start Console's local server, `uv run samepage connect`, import `switch/samepage.template.yaml` and use it, `uv run samepage wire-rooms`, `make arbiter`. In the samepage-ask room (no @mention needed there):

```
ask <question>          patrol [full | on <ref> | holdout]
approve <case> [why]    override <case> <file>     reject <case> <why>
trust                   history <case or topic>    show <case>    receipt <case>
```

## Outcome states

| State | Meaning | Action |
|---|---|---|
| `VERIFIED` | Agents agree, quotes verified, no doc contradicts, same wording everywhere | Answer marked verified |
| `COMPATIBLE` | Agree, docs word it differently ("24/7" vs "round-the-clock") | Treated as agreement, no alarm |
| `CONFLICT` | Agents disagree (or one found nothing) | Card + owners rule |
| `SOURCE_CONFLICT` | Agents agree, but another doc says otherwise | Card + owners rule |
| `UNSUPPORTED` | No doc covers it, a quote failed, an answer failed, or the agreement can't be cross-checked | Never shown as fact |
| `RESOLVED` | Ruled, PR open, retest passed on the fix branch | Human merges |

## Evaluation

Real runs: `patrol full` asked both agents all 36 golden questions (C1–C6, 6 wordings each), sealed, on `main` of the drifted docs repo; `make eval` scored the recorded answers. Copied from [`reports/eval-20261106T220548Z.md`](reports/eval-20261106T220548Z.md) (2026-11-06 22:05 UTC, commit `8d53033`, answers in `reports/answers-20261106T220244Z.jsonl`):

| Metric | Result | Target |
|---|---|---|
| Question equivalence accuracy | 29/30 = 0.97 | ≥ 0.9 |
| Conflict detection precision | 0.94 (TP 17, FP 1) | ≥ 0.90 |
| Conflict detection recall | 0.94 (FN 1) | ≥ 0.80 |
| False alarm rate on COMPATIBLE | 0.08 (1/12) | 0 |
| Exact state accuracy | 0.64 (23/36) | n/a |
| Evidence validity (claims with verified quotes) | 0.96 (110/114) | 1.00 of displayed claims |
| Both agents right and consistent (before fix) | 0.37 (11/30) | n/a (after-fix comes from retest) |

**Held-out H1** (audit log retention, never seen during development; inserted only on branch `holdout/h1`), from [`reports/eval-holdout-20261106T220951Z.md`](reports/eval-holdout-20261106T220951Z.md) (2026-11-06 22:09 UTC, commit `8d53033`):

| Metric | Result | Target |
|---|---|---|
| Conflict detection precision | 1.00 (TP 6, FP 0) | ≥ 0.90 |
| Conflict detection recall | 1.00 (FN 0) | ≥ 0.80 |
| False alarm rate on COMPATIBLE | not run (0/0) | 0 |
| Exact state accuracy | 0.00 (0/6) | n/a |
| Evidence validity (claims with verified quotes) | 0.95 (18/19) | 1.00 of displayed claims |
| Both agents right and consistent (before fix) | 0.00 (0/6) | n/a (after-fix comes from retest) |

**H1 detected: 6/6.** All six came back `SOURCE_CONFLICT`, not the expected `CONFLICT`: both agents read the spec correctly (365 days), and SamePage still found the pricing page saying 90.

**After the fix:** the live retest of C1 on the fix branch went from 0/4 to 4/4 (both agents right and consistent), case RESOLVED.

**Reading the numbers honestly:**
- Expected states were written assuming the agents would disagree on C1, C2 and H1. With the real agents they agreed on the right answer, so most of those rows are `SOURCE_CONFLICT`: still an alarm, still the right sources blamed, but not an exact match. That is why exact state accuracy is low while recall is high.
- The misses are SamePage's, not the agents': see the first three items under Known limitations. We did not change the engine and re-score these answers; that would be tuning on the evaluation.

## Architecture

A Python service (FastAPI, Pydantic v2, SQLite in WAL mode) with no model calls of its own: the agents read, the engine verifies, normalizes, scans and classifies with plain code. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the ADRs:
[0001 Switch integration](docs/adr/0001-switch-integration.md) ·
[0002 deterministic engine](docs/adr/0002-deterministic-engine.md) ·
[0003 docs in git, batches, fixer](docs/adr/0003-docs-in-git-batch-dispatch-fixer.md) ·
[0004 patrol, blast radius, owners, trust](docs/adr/0004-patrol-blast-radius-owners-trust.md).
Plain-language tour: [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md).

## Security

- **Docs are data:** lines that read like instructions to AI are excluded from facts and shown as ignored; a test proves an injected line changes no outcome.
- **Least privilege:** the engine's GitHub token is fine-grained, one repo, read-only. The fixer opens PRs with the `gh` sign-in on the machine that runs it, and is instructed to touch only the docs repo; every PR still has to pass the diff guard, and SamePage has no merge call. (Console's GitHub connector, which can scope a grant to one repo, needs an https server address; a local server is http.)
- **Diff guard:** a PR is refused unless it targets `main` from `samepage/<case>`, is open, changes only lines inside the approved passages (with a cap on added lines), and has no renames, mode changes, or new, deleted or binary files. The retest runs at the exact commit that was checked.
- **Authority in code:** approvers can make any ruling; owners of the losing docs can only approve the proposal. Approvers can be configured by the sender's unique id.
- **Sealing in code:** a desk reply counts only if it comes from that desk's agent and names a batch that is still open; stale, untagged or echoed messages are dropped.
- **Untrusted input:** agent replies are size-capped and schema-validated, never executed. Git refs are validated. The audit log is append-only, enforced by database triggers.
- Secrets only via `.env` (gitignored); gitleaks runs in CI and pre-commit; `bandit` and `pip-audit` report no findings.

## Known limitations

- **Plan read from the wrong field (1 false CONFLICT, C1).** Claude Code answered "upgrade to Enterprise" with the qualifier "non-Enterprise plans"; the engine took the plan from the qualifier (Enterprise) and read it as yes.
- **Table cells (1 UNSUPPORTED, C3).** A quote of a table row (`| Seats per workspace | 5 | 250 | Unlimited |`) has no plan or unit next to the number, so the engine can't confirm the quote states "5 seats" for Starter. It refuses rather than guesses.
- **Yes/no versus a schedule (the 1 COMPATIBLE false alarm, C4).** "Is support available on weekends?": one agent answered "yes, including weekends and holidays", the other "24/7"; the engine compares those as different values.
- **Blast radius can over-reach.** For two H1 wordings the scan also listed a changelog line about the trash keeping deleted items for 30 days, because it shares "keep", "deleted" and a number of days with the question.
- **One machine.** The demo runs on Switch Console's local server; the agents, the arbiter and the `gh` sign-in all live on the presenter's Mac.
- **Lexical question matching:** "Does Juniper Desk support HIPAA?" maps to the support-hours question (the one miss in 30), and "Is there phone support?" scores 0.72 against support hours. A sentence-embedding backend can be plugged in (`Embedder` protocol).
- **Value types are limited** to durations, seats, rates, 24/7 schedules, yes/no and plan availability. Other values are compared as text and not cross-checked across the docs.
- **The 90-second answer target** depends on agent speed; the default timeout is 240 s.
- **Conservative by design:** answers whose value is free text, or a yes/no with no plan named, end `UNSUPPORTED` even when the agents are right, because the engine can't cross-check them.
- **The glossary and normalizer were written alongside the demo corpus.** The rules are generic, but the glossary groups cover the planted topics; a real deployment has to keep `corpus/glossary.yaml` up to date. Nothing was tuned on H1.
- **Sender check assumption:** desk replies are accepted only when Switch reports the agent's name or id as the sender. This is unverified until the live run (U5; `SAMEPAGE_STRICT_SENDER=false` relaxes it).
- Pending fix briefs are kept in memory, so restarting the arbiter mid-fix means re-approving.
- The HTTP API has no login; Docker binds it to localhost only.
- `make up` is untested here: Docker wasn't available in the build environment.
- An independent QA/Security review found 6 high and 5 medium issues; all are fixed and tested (see [docs/REVIEW.md](docs/REVIEW.md)).

## What we'd build next

- **Block drift before it ships:** run SamePage as a check on every docs pull request, and hold back a change that contradicts the approved spec.
- **Nightly patrol:** schedule `patrol` and post a morning report of new contradictions.
- **A guard behind one customer-facing bot:** a company with a single support chatbot runs SamePage behind it, so wrong facts are caught before the bot repeats them.
- **Where teams already chat:** the same rooms over Switch's other chat bridges.
- More value types (table cells, yes/no versus schedules), sentence embeddings for question matching, and per-team trust trends.

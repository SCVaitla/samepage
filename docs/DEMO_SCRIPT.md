# Demo video script (≤ 3:00)

The submitted video (about 2:40) is a captioned walkthrough of screenshots from the live run on 2026-11-06 (real Switch, Claude Code, Codex and GitHub). Every screen in it is real output; nothing is mocked.

| # | Shows | Caption says |
|---|---|---|
| 1 | Title | Two AI agents agreeing isn't proof. SamePage finds the docs behind wrong answers, gets a human to rule, and proves the fix. |
| 2 | The problem | Product facts live in many docs that drift apart; AI repeats whichever it reads. |
| 3 | The idea | The consensus trap: two agents reading the same stale page agree and are both wrong, so SamePage checks every doc even when they agree. |
| 4 | The workflow | Ask → sealed answers in private rooms → quotes checked, all docs scanned → card → human approves → fixer PR → retest → receipt. |
| 5 | Switch template | One template creates 3 agents and 5 rooms. |
| 6 | Smoke room | Claude Code and Codex live in one room (Gate 0). |
| 7–8 | The real card (`show db1488ad`) | Both agents correctly say no; SamePage still finds the website and sales FAQs saying yes, names their owners, ignores a planted injection line. |
| 9 | samepage-fix | The owner approves; the fixer opens PR #1. |
| 10 | PR #1 on GitHub | Only the approved lines change ("Yes" → "No, Enterprise only"). |
| 11 | Retest card | 0/4 before → 4/4 after, RESOLVED. |
| 12 | Resolution receipt | One summary from the audit records. |
| 13 | A private desk during `patrol holdout` | The held-out questions answered in the JSON contract; caught 6/6. |
| 14 | Results | Precision/recall 0.94/0.94, question matching 0.97, held-out 6/6, 87 tests, 93% coverage; misses listed in the README. |
| 15 | Why Switch | SamePage is a Switch agent; sealing relies on room membership; without Switch it stops. |

To re-record live instead: follow `docs/RUNBOOK.md`, ask the SSO question in samepage-ask, `approve` it, wait for the retest and receipt, then show the README evaluation.

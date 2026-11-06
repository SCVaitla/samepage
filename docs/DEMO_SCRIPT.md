# Demo video script (≤ 3:00)

Record against the live setup (`docs/RUNBOOK.md`). Agent waits may be sped up; say "sped up" on screen when you do.

| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | Title card | "Ask two AIs the same question and you get two answers. We made that the alarm." |
| 0:15–0:25 | Switch Console: the SamePage room group (ask, two private desks, fix) | "Everything runs in Switch. Each agent answers in its own private room, so neither can copy the other." |
| 0:25–1:05 | `@samepage-arbiter ask Does the Starter plan include single sign-on?` → the desks working → the card | "Claude Code says yes, Codex says no. SamePage checks every quote against the file, then scans all our docs. The blast radius shows the wrong 'yes' in two places, the website and the sales FAQ, and pings their owners. And it ignored a line in the help center trying to instruct AI agents." |
| 1:05–1:35 | `@samepage-arbiter patrol` → drift report with the seats SOURCE_CONFLICT | "Patrol re-asks everything we know. Here both agents agree Starter has 10 seats, and they're both wrong: the approved spec says 5. Agreement isn't proof." |
| 1:35–2:15 | `approve <case>` → fix room brief → PR on GitHub (show the small diff) → retest card "0/3 → 3/3", RESOLVED | "The owner approves in the room. A fixer agent opens a PR that touches only those lines; SamePage checks the diff, retests both agents on the branch, and a human merges." |
| 2:15–2:35 | `@samepage-arbiter trust` → ledger; then `reports/eval-*.md` | "Over time the trust ledger shows which docs keep being wrong. And here are our real eval numbers, including a held-out case we never tuned on." *(Read the real numbers from the report. Never script them.)* |
| 2:35–3:00 | README "How Switch is used" | "Without Switch there are no sealed rooms, no agents to compare, and no place for the human to rule. Next: patrol on every docs push, and more value types." |

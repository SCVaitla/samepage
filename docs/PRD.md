# SamePage — Product Requirements

**Product Manager.** Reviewed by QA + Security (see "Gate 1 review" at the end). Juniper Desk is fictional.

**One-liner:** SamePage turns disagreements between AI agents into an investigation, a human decision, and a verified fix.

**Users:** a *teammate* asks product questions; an *owner* (product, marketing, sales or support lead) rules on cases about their docs; an *approver* may rule on any case.

Room commands are `@samepage-arbiter <command>`. Switch does not forward custom slash commands to agents (ADR 0001, V8), so the brief's `/approve` became `@samepage-arbiter approve`.

## User stories and acceptance criteria

| ID | Story | Acceptance criteria (testable) |
|---|---|---|
| US-1 Ask | As a teammate, I ask a product question in the room and get one response labeled with one outcome state. | `ask <q>` produces exactly one card naming one of the six states. Time to the card ≤ 90 s with live agents is a **target, measured in the live run**; the agent timeout is configurable (default 240 s). |
| US-2 Independence | Each agent's first answer is recorded before either sees the other's. | Each worker answers in its own private desk; workers are not members of each other's desk or the ask room. The first reply per worker per case is stored with SHA-256 and time; later replies are ignored. The audit log has `dispatched` → `answer_sealed` (×2) → `revealed` for each case. |
| US-3 Evidence | Every claim shown includes file, line span and a verbatim quote that was verified. | Quotes are checked character for character (whitespace runs = one space) within ±2 lines. Claims that fail are dropped and listed as dropped. Quotes citing injected instructions are refused. |
| US-4 Detect | Incompatible → CONFLICT; agreeing agents with contradicting sources → SOURCE_CONFLICT; paraphrased-but-equal → COMPATIBLE. | Planted cases C1–C5 give these states from hand-written agent answers; the engine finds contradicting passages by scanning the corpus. |
| US-5 Decide | The owner can approve, override or reject from the room; recorded with who/when/why. | `approve`, `override <file>` and `reject <why>` work only for approvers or owners of losing sources. Decisions are stored with user, choice, truth, winners, losers, rationale and time. |
| US-6 Fix | After approval, a PR changes only the outdated text, with evidence and decision in the body; never auto-merged. | The fixer gets a brief listing exact files and line spans. The arbiter refuses a PR whose diff touches anything else, whose branch isn't `samepage/<case>`, or that is merged or closed. No merge call exists. One PR per case. |
| US-7 Retest | The question and paraphrases are re-asked on the PR branch; before/after posted. | Retest asks N questions on `main` and on the branch. The card shows "x/N before → y/N after" (both agents right and agreeing). RESOLVED only when y = N. |
| US-8 Audit | `history <case or topic>` returns the decision trail. | The audit log is append-only (DB triggers refuse UPDATE/DELETE). `history <case>` lists events; `history <topic>` lists matching cases with their states and rulings. |
| US-9 Safe failure | Timeout, invalid JSON or a failed call never ends VERIFIED. | A timeout, invalid JSON, contract violation, missing batch block or unverified headline quote all give UNSUPPORTED with the reason on the card. Handler crashes are posted to the room. |
| US-10 Patrol *(new)* | As a docs owner, I want drift found before customers find it. | `patrol` re-asks every known canonical question; `patrol full` adds paraphrases and records answers to `reports/answers-*.jsonl`. The report lists alarms first, with case ids and how many places are wrong. |
| US-11 Blast radius *(new)* | As an owner, I see everywhere a wrong fact appears. | Alarm cards list every passage holding a losing value, with its team (surface) and owner, deduplicated. |
| US-12 Owner routing *(new)* | The people who own the wrong docs are asked, and may rule. | Owners of losing sources are @mentioned on the card and pass `can_rule`; others (not approvers) are refused with a message naming the owners. |
| US-13 Trust ledger *(new)* | As a manager, I see which docs keep being wrong. | `trust` ranks source families by rulings lost; rejects are excluded. |
| US-14 Injection *(C7)* | Docs are data. | Lines that read like instructions to AI are excluded from every extracted fact and shown as ignored. Removing the injected line changes no outcome. |

## Non-goals

As in the brief, section 2.2: no training, no web frontend, no integrations beyond Switch, Mattermost, GitHub and the two coding agents, no real company data.

## Gate 1 review (QA + Security roles)

- **QA:** every story maps to at least one automated test (see `docs/TRACEABILITY.md`). US-1's 90-second target and the live halves of US-2, US-6 and US-7 can only be measured in the live run, and are marked that way.
- **Security:** the owner-routing threat (anyone who can address the arbiter could approve) is handled in code (`decide.can_rule`). The GitHub token is read-only in the engine, and the fixer's write access comes from the deployer's Switch connection, scoped in the template. Agent output and docs are validated, size-capped and never executed.

# Walkthrough: how SamePage works, in plain words

Read this before the demo. Each section names the file to open if a judge asks "show me".

## The idea in one breath

Ask two different AI agents the same question without letting them see each other's answer. If they disagree, the docs they read probably disagree too. SamePage turns that disagreement into evidence, a human decision, a pull request, and a retest that proves the fix.

## 1. Switch is the backbone (`switch/samepage.template.yaml`, `samepage/arbiter.py`)

- One template creates three agents (Claude Code worker, Codex worker, fixer) and four rooms.
- SamePage itself is a Switch **agent** called `samepage-arbiter`. It listens to its rooms over a server-sent-events stream and posts with plain HTTP (`samepage/switch_client.py`).
- **Why the answers are sealed:** each worker has its own private "desk" room, and Switch only lets an agent read rooms it belongs to. The arbiter posts the question in both desks, waits for both replies, saves a fingerprint (SHA-256) and time for each, and only then shows both answers together in the ask room. Workers never join the ask room, so they never see the reveal.
- People talk to the arbiter with @mentions (`@samepage-arbiter ask …`), because Switch doesn't forward custom slash commands to agents.

## 2. What the agents send back (`samepage/models.py`, `samepage/parse.py`)

Each answer is a JSON block: a plain answer plus claims. A claim is *what* (entity, attribute, plan), *the value*, *where* (file, lines) and *the exact quote*. Anything that isn't valid JSON in this shape becomes an error, and errors can never end up "verified".

## 3. Checking the evidence (`samepage/evidence.py`)

For every claim, SamePage opens the cited file and checks that the quote is really there, word for word, within two lines of where the agent said. If not, the claim is dropped. A made-up quote can't sneak through.

## 4. Comparing values (`samepage/values.py`)

"14 days", "two weeks" and "14-day" all become `days:14`. "1k rpm" and "1,000 requests per minute" both become `per_min:1000`. "Enterprise only", asked about Starter, becomes `bool:false`. These are general rules about units and wording. No rule knows which facts are planted in the demo docs.

## 5. Looking beyond what the agents read (`samepage/classify.py`, `Engine.scan`)

This is how SamePage catches the case where **both agents agree and are both wrong**. It scans every doc for other passages about the same fact: same topic word (using the company glossary, so "SSO" = "single sign-on"), same plan, and a value of the same kind. If both agents say "10 seats" but the product spec says "5 seats", that's a SOURCE_CONFLICT.

## 6. Deciding the outcome (`Engine.evaluate`)

The rules are applied in order, and the first match wins:

1. An answer failed → UNSUPPORTED
2. Neither agent found it → UNSUPPORTED
3. A headline quote didn't verify → UNSUPPORTED
4. One found it, one didn't → CONFLICT
5. The values differ → CONFLICT
6. They agree, but another doc disagrees → SOURCE_CONFLICT
7. They agree and the docs agree in different words → COMPATIBLE
8. They agree and everything says it the same way → VERIFIED

There is no AI in this step, so the same input always gives the same verdict.

## 7. The card (`samepage/cards.py`)

The card shows both sealed answers, the reason, an evidence table (value, file and lines, source and authority, who found it, quote), and then:
- **Blast radius:** every place the wrong value appears, and which team reads it.
- **Proposed truth:** the value from the most authoritative source. This is advice; a person decides.
- **Owners asked to rule:** the owners of the wrong docs, from `corpus/sources.yaml`.
- **Ignored text:** lines in the docs that try to instruct AI agents, shown and never used.

## 8. The human decides (`samepage/decide.py`)

`approve` accepts the proposal, `override <file>` makes that file the truth, and `reject <why>` closes it. Only approvers or the owners of the wrong docs may rule. Every decision is stored with who, when and why, in an audit log that the database refuses to change or delete (`samepage/migrations/001_init.sql`).

## 9. The fix and the proof (`samepage/fixer.py`, `Arbiter.retest`)

The fixer agent gets a brief listing exactly which lines to change. It opens a PR on `samepage/<case>`. SamePage then reads the PR's diff from GitHub and refuses it if anything outside those lines changed. Then it asks both agents the question and its paraphrases again, on `main` and on the fix branch, and posts "0/3 before → 3/3 after". A person merges; SamePage never does.

## 10. Patrol and the trust ledger (`Arbiter.patrol`, `samepage/trust.py`)

`patrol` re-asks every known question, so drift is found before a customer finds it. `trust` shows which docs keep losing rulings: the place where knowledge rots.

## 11. How we know it works (`tests/`, `samepage/evaluate.py`)

- 64 automated tests, 94% coverage, including property tests (for example, swapping the two agents never changes the verdict) and a full flow with a fake Switch room, fake agents and a fake GitHub.
- `make eval` scores *real* recorded agent answers. Until a live patrol has been recorded, it says "not run" instead of showing numbers.
- H1, the held-out case, is only inserted into a temporary copy (or a separate branch), and nothing was tuned on it.

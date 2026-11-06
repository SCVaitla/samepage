# ADR 0004: New features: drift patrol, blast radius, owner routing, source trust ledger

- **Status:** Accepted (approved by the human on 2026-11-05)
- **Date:** 2026-11-05
- **Roles:** Product Manager (author), Architect, Security Engineer

## Context

With about 39 hours left, the human asked for a stronger idea. A feature had to reuse the pipeline we were building anyway and make the business story clearer to judges. Anything needing a new integration or a new UI was out.

## Decision

| Feature | What the room sees | Built from | Code |
|---|---|---|---|
| **Drift patrol** | `@samepage-arbiter patrol` re-asks every known question (both agents, sealed) and posts a drift report; `patrol full` adds every paraphrase and records the answers for `make eval` | The batch collector + classifier | `Arbiter.patrol`, `patrol.patrol_report` |
| **Blast radius** | Each alarm card lists every place the disputed value appears, which team reads it, and how many teams are affected | The corpus scan that already powers SOURCE_CONFLICT | `cards.blast_radius` |
| **Owner routing** | Owners of the losing sources are @mentioned and **may approve** the proposal (override and reject need an approver); the fix brief and PR body name the passages | `owner` per source family in `corpus/sources.yaml` | `cards.owners_to_notify`, `decide.can_rule` |
| **Source trust ledger** | `@samepage-arbiter trust` ranks source families by how often they lost a ruling | The decisions table | `trust.ledger` |

**Cut list change:** `history` stays (it was cheap), but the trust ledger is the feature we demo. The brief's cut order otherwise stands.

## Security notes

- **Owner routing widens who can rule, so owners can only approve.** Authority is checked in engine code (`decide.can_rule`). Approvers (`SAMEPAGE_APPROVERS`, matched against the sender's name or unique id) may do anything. Owners of *losing* sources may only approve the proposal: after the independent review (M1), they can no longer override to make their own doc the truth. Switch addressing only controls who can wake the arbiter. Usernames are compared case-insensitively without the `@`.
- Patrol answers are written to `reports/answers-*.jsonl` and committed alongside the eval reports, so every published number can be traced to its inputs. They hold agent output about fictional docs, never secrets.

## Consequences

- The demo story becomes proactive: drift is found before a customer does.
- A patrol of all 36 golden questions is 6 batches per desk. Expect several minutes with real agents.

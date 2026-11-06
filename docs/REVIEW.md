# Independent QA + Security review (2026-11-05)

The brief asks for a reviewer that did not write the code to check each phase before a gate closes. A separate agent reviewed the repo at commit `39c277b`. It read the code and docs, ran `make check`, and probed behaviour with its own scripts. It changed nothing. Below is every finding it reported, and what we did about each.

"Confirmed" means the reviewer reproduced it by running code. Every fix has a test that fails without it.

| # | Sev | Finding | Fix | Test |
|---|---|---|---|---|
| H1 | high | The claimed value was never checked against its quote: a real but unrelated line, or a quote stating a different value, gave VERIFIED (confirmed) | `Engine.check`: the quoted passage must share a topic word with the question, and the quote must state the claimed value | `test_classify.py::test_real_but_irrelevant_quote_is_not_evidence`, `::test_quote_that_contradicts_the_claimed_value_is_not_evidence` |
| H2 | high | Agreement on values the engine can't cross-check came out VERIFIED (confirmed) | Such agreement is now UNSUPPORTED (rule 6b) | `::test_agreement_that_cannot_be_cross_checked_is_never_verified` |
| H3 | high | Which docs got scanned depended on one agent's entity name (confirmed) | Topic words come from the question plus every agent's claims, minus generic and size words | `::test_scan_does_not_depend_on_one_agents_entity_name` |
| H4 | high | Stale or untagged desk replies could be sealed to the wrong case (confirmed) | Replies need an open `[batch <id>]` tag; otherwise they are dropped | `test_arbiter.py::test_replies_without_an_open_batch_tag_or_from_others_are_dropped` |
| H5 | high | The diff guard missed renames, mode changes, new/binary/empty files, removed lines starting `-- `, huge insertions, and neighbouring-line edits (confirmed) | Strict parser: headers read only between hunks using the `@@` counts; file-level changes refused; no slack; cap on added lines | `test_diff_guard.py` (5 tests) |
| H6 | high | RESOLVED could be set while the docs still conflicted (confirmed) | `consistent()` also needs a VERIFIED/COMPATIBLE outcome and uses each agent's first claim only | `test_fixer_trust_equivalence.py::test_retest_counts_only_clean_outcomes` |
| M1 | med | An owner of a losing doc could override in their own favour (confirmed) | Owners may only approve; override and reject need an approver | `test_arbiter.py::test_owner_of_a_losing_source_may_rule` |
| M2 | med | PR base not checked; head commit not pinned (inferred) | Base must be `main`; the head SHA is stored (migration 002) and the "after" retest runs at that commit | `::test_pr_against_another_base_is_refused_and_duplicates_retest_once` |
| M3 | med | Authority used the changeable display name; any desk member could answer as the worker; echoed dispatches could be sealed (partly confirmed) | Approvers match the sender's name *or* unique id; desk replies only from that desk's agent; our own dispatch echoes ignored | `::test_replies_without…` |
| M4 | med | Normalizer: negation after the plan, "Starter: no", "forty-five", "12 months" vs "one year" (confirmed) | Negation checked after the plan up to a comma; full number words to 999; whole years of months = 365 days | `test_values.py::test_review_normalizer_cases` |
| M5 | med | Signs of tuning: the number words were the planted values; the glossary covers the planted topics | Number words are now generic. The glossary is disclosed under Known limitations; nothing was tuned on H1 | — |
| L | low | Duplicate fix replies started two retests; one desk gave a "second opinion" of one; the API has no login and was published on all interfaces; doc counts were wrong | The pending fix is taken atomically; at least 2 desks and 2 answers are required; Docker binds to localhost; docs corrected | `::test_pr_against_another_base…`, `::test_one_desk_is_not_a_second_opinion`, `test_classify.py::test_a_single_answer_is_never_enough` |

The review also surfaced one more bug while we fixed H3: glossary phrases matched inside their own group tokens ("plan" inside "g:plan"). Fixed in `samepage/text.py`.

**Not fixed, disclosed:** pending fix briefs live in memory, so a restart means re-approving. The sender check assumes Switch reports the agent's name or id as the sender (to confirm in the live run, U5).

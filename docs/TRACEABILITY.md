# Traceability: stories → tests

Status as of commit on 2026-11-05. "Unit/integration" tests run in CI (`make test`); "live" means the Gate 4 run against a real Switch server, real agents and GitHub, which has **not happened yet**.

| Story | Automated tests (all passing) | Live check (pending) |
|---|---|---|
| US-1 Ask | `test_arbiter.py::test_full_flow_ask_conflict_approve_pr_retest_resolved`, `test_io.py::test_api_health_evaluate_limits_and_validation` | Time from ask to card |
| US-2 Independence | `test_arbiter.py::test_full_flow…` (one dispatch per desk; audit has `answer_sealed`, `revealed`), `::test_replies_without_an_open_batch_tag_or_from_others_are_dropped`, `test_parse_store.py::test_store_seals_first_answer_only_and_audit_is_append_only` | RUNBOOK steps 6–7 (membership, cross-desk read refused) |
| US-3 Evidence | `test_evidence.py` (11 tests incl. 3 hypothesis properties), `test_cases.py::test_c6_invented_hipaa_quote_is_unsupported_not_verified`, `test_classify.py::test_real_but_irrelevant_quote_is_not_evidence`, `::test_quote_that_contradicts_the_claimed_value_is_not_evidence`, `::test_agreement_that_cannot_be_cross_checked_is_never_verified` | — |
| US-4 Detect | `test_cases.py::test_c1…c5`, `test_classify.py::test_comparison_is_symmetric` (hypothesis), `::test_scan_does_not_depend_on_one_agents_entity_name`, `::test_verified_when_agents_agree_and_no_doc_disagrees` | `make eval` on a recorded `patrol full` |
| US-5 Decide | `test_arbiter.py::test_rulings_need_authority_and_support_override_and_reject`, `::test_owner_of_a_losing_source_may_rule` | — |
| US-6 Fix | `test_diff_guard.py` (renames, modes, new/deleted/binary files, header-looking lines, big insertions, neighbouring lines), `test_fixer_trust_equivalence.py` (guard, brief, idempotency property), `test_arbiter.py::test_pr_against_another_base_is_refused_and_duplicates_retest_once`, `test_arbiter.py::test_pr_touching_other_lines_is_refused_and_not_retested`, `test_io.py::test_github_reads_pr_and_rejects_other_repos` | Real PR on the demo repo |
| US-7 Retest | `test_arbiter.py::test_full_flow…` ("0/3 before → 3/3 after", state RESOLVED), `test_fixer_trust_equivalence.py::test_retest_counts_only_clean_outcomes` | Retest on the real fix branch |
| US-8 Audit | `test_parse_store.py` (append-only triggers), `test_arbiter.py::test_full_flow…` (history by case and topic) | — |
| US-9 Safe failure | `test_classify.py::test_timeout_or_bad_json_is_unsupported_never_verified`, `::test_a_single_answer_is_never_enough`, `test_arbiter.py::test_one_desk_is_not_a_second_opinion`, `test_arbiter.py::test_silent_agent_times_out_to_unsupported`, `test_parse_store.py::test_parse_*` | — |
| US-10 Patrol | `test_arbiter.py::test_patrol_finds_the_drift_and_records_answers` | `patrol full` live |
| US-11 Blast radius | `test_cases.py::test_c1…` (sales FAQ in the losing set), `test_arbiter.py::test_full_flow…` ("Blast radius" on the card) | — |
| US-12 Owner routing | `test_arbiter.py::test_full_flow…` (@marketing-lead, @sales-lead mentioned), `::test_owner_of_a_losing_source_may_rule` | — |
| US-13 Trust ledger | `test_fixer_trust_equivalence.py::test_trust_ledger_counts_wins_and_losses`, `test_arbiter.py::test_full_flow…` (`trust`) | — |
| US-14 Injection | `test_cases.py::test_c7_injected_line_is_reported_and_never_used`, `test_classify.py::test_injected_line_changes_nothing` | — |
| Question equivalence | `test_fixer_trust_equivalence.py::test_equivalence_meets_target_on_golden_paraphrases` (29/30) | — |

# ADR 0003: Docs live in git; questions go out in batches; a fixer agent opens the PR behind a diff guard

- **Status:** Accepted (live behaviour still to confirm in the Gate 0 run; see ADR 0001, U1–U5)
- **Date:** 2026-11-05
- **Roles:** Agent Engineer (author), Architect, Security Engineer

## Context

Retesting "against the PR branch" means the agents must read the docs as they are on a given git ref, with stable line numbers. Patrol and retest ask many questions, and agent round trips are the slowest part of the system. The fix itself must touch only the approved text and must never be merged by a machine.

## What we verified in Switch (commit 7e1316f)

- An agent's **`repo:`** field makes Switch Console clone that repository into the agent's directory before the agent first runs (`docs/TEMPLATES.md`, "The agent block", `repo`).
- **`connections: [{service: github, access: write}]`** grants the deployer's GitHub connection to an agent (same section, `connections`).
- **`allow_existing: true`** lets a template reuse an agent that already exists (field reference).
- Not verified, from memory: Mattermost caps post length (16,383 characters by default, as far as we recall). Batches are capped (see below) so a reply of 6 JSON blocks stays well under that. Check this on the live server (`docs/RUNBOOK.md`, step 9).

## Decision

1. **Docs in a git repo.** Every worker gets the demo docs repo through `repo:`. A request carries `[ref <ref>]`, and the worker runs `git fetch origin && git checkout --detach origin/<ref>` before reading. The engine reads the same ref from its own clone with `git show origin/<ref>:<path>` (`Corpus.from_git`; refs are validated against a strict pattern). Line numbers therefore match on both sides.
2. **Batch dispatch.** The arbiter sends each desk *one* message with up to `SAMEPAGE_BATCH_SIZE` (default 6) numbered questions. The worker replies once, with one JSON block per question. Each question is its own sealed case. A timeout or a missing block becomes UNSUPPORTED for that question only.
3. **Fixer agent + diff guard.** After an approve or override, the arbiter posts a fix brief in `samepage-fix`: the exact files and line spans, the current text, the approved truth, and the PR body. The fixer (Claude Code with a GitHub write connection) pushes `samepage/<case-id>` and opens the PR. The arbiter then reads the PR through the GitHub API (read-only, fine-grained token) and refuses it unless:
   - the head branch is `samepage/<case-id>`,
   - the PR is open and unmerged,
   - every changed line falls inside an approved span (±1 line), and every approved file was changed.
   Only then does it retest. **No code path in SamePage merges.**
4. **Retest = before and after.** The case's question plus up to `SAMEPAGE_RETEST_QUESTIONS - 1` paraphrases are asked on `main` and on the fix branch. The case is RESOLVED only when both agents give the approved truth on every question after the fix.

## Rejected

- **The engine writes the patch itself.** Rewording "included on all plans" into correct, on-tone copy is a language task. Doing it in code would be brittle, so the fixer agent does the wording and the engine checks scope.
- **Room `docs:` instead of git.** There's no ref concept, so there's no retest against a branch.

## Consequences

- The demo needs a GitHub repo for the docs and a fine-grained token. That's an external account action, so the human creates both.
- Retest costs two agent rounds (main, then the branch). The video may speed this up, and the runbook says so.

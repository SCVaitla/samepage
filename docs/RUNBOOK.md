# Runbook: from a fresh clone to a live demo (and Gate 0)

**Who:** you, on your Mac. **Time:** about 60–90 minutes the first time, mostly installs and sign-ins.
Put screenshots in `docs/evidence/` under the names given. Anything that differs from "Expected" is a finding: write it down.

## 0. Prerequisites

```sh
node -v            # v20 or later (Switch Console needs it). Missing: brew install node
uv --version       # Missing: brew install uv
git --version
docker info        # only for the built-in Mattermost; Docker Desktop must be running
claude --version   # Claude Code, signed in. Missing: npm i -g @anthropic-ai/claude-code, then run `claude` once
codex --version    # Codex, signed in
gh auth status     # optional, handy for creating the docs repo
```

## 1. Clone and set up SamePage

```sh
git clone <this repo> samepage && cd samepage
make setup        # installs locked deps, creates .env
make check        # lint, types, tests with coverage, security; should all pass
make seed         # shows the corpus: 12 files, owners, 1 ignored injection line
```

## 2. Create the demo docs repo (an external account action: you do it)

```sh
gh repo create juniper-desk-docs --private --clone   # or create it on github.com and clone it
make demo-reset DOCS=$PWD/juniper-desk-docs          # copies the drifted corpus in
git -C juniper-desk-docs add -A && git -C juniper-desk-docs commit -m "docs: Juniper Desk (fictional)" \
  && git -C juniper-desk-docs push -u origin main
```

On GitHub: **Settings → Branches → add a rule for `main`: require a pull request before merging.** SamePage never merges, and this makes sure nothing else can either.

Create a **fine-grained token** (GitHub → Settings → Developer settings → Fine-grained tokens) with access to **only** `juniper-desk-docs` and **Contents: Read** and **Pull requests: Read**. The engine only reads PRs; the fixer agent writes through your Switch GitHub connection. Put it in `.env`:

```
GITHUB_TOKEN=<token>
GITHUB_DEMO_REPO=<you>/juniper-desk-docs
SAMEPAGE_DOCS_REPO_DIR=/absolute/path/to/juniper-desk-docs
```

## 3. Switch Console, server, Mattermost

1. Install Switch Console: https://github.com/sandbox-quantum/switch/releases/latest (`switch-console-arm64.dmg` on Apple Silicon).
2. **Setting up Switch → Add a server → Run a server on this computer**, with **Also run Mattermost** on. Wait for **Running locally**.
3. **Set up agent providers:** Claude Code and Codex both installed and signed in.
4. **Home → Messaging apps → Mattermost → Link → This is me.**
5. **Settings → Connections → GitHub:** connect it, with access to `juniper-desk-docs` (the fixer uses it).

## 4. Register the arbiter

1. Find the server's **API (bridge) URL** in Console. `curl <url>/health` must return 200.
2. Mint a **personal registration key** in the Gateway, labelled `samepage-arbiter` (the endpoint is `POST /api-keys`; the menu wording isn't verified). Use **your** key, not the bootstrap key, so the arbiter has the same owner as the workers (ADR 0001, V5/V6).
3. In `.env`: set `SWITCH_API_URL` and `SWITCH_REGISTRATION_TOKEN`, and set `SAMEPAGE_APPROVERS=<your Mattermost username>`.
4. `uv run samepage register` appends `SWITCH_AGENT_ID` and `SWITCH_AGENT_API_KEY` to `.env`.

## 5. Create the rooms from the template

Console → **Templates → paste** `switch/samepage.template.yaml` → set **Docs repository URL** to `https://github.com/<you>/juniper-desk-docs` and **Docs repository (owner/name)** to `<you>/juniper-desk-docs` (the fixer's GitHub grant reaches only that repo) → **Create**.

📸 `01-template-created.png`

**Gate 0, item 1:** the `samepage-smoke` kickoff asks both workers to name themselves. 📸 `02-smoke-two-agents.png`. Delete `samepage-smoke` afterwards.

## 6. Wire the arbiter to the rooms

```sh
uv run samepage rooms     # note the ids of samepage-ask, both desks and samepage-fix
```

In `.env`:

```
SAMEPAGE_ASK_ROOM=<id>
SAMEPAGE_DESKS=samepage-claude=<desk-claude id>,samepage-codex=<desk-codex id>
SAMEPAGE_FIX_ROOM=<id>
```

Then start it and leave it running: `make arbiter`.
If posts fail with `404 … Agent client not running` (open question U1), stop and capture the log. There's a fallback (the `connect_to_room` op).

## 7. Sealed independence (Gate 0, item 2)

In **samepage-ask**: `@samepage-arbiter ask Does the Starter plan include single sign-on?`

Expected: the "asking 2 agents separately" message; one batch request in each desk; each worker replies with a JSON block; one card in the ask room with both answers revealed together.

📸 `03-desk-claude.png`, `04-desk-codex.png`, `05-card.png`

Isolation checks:
- In each desk, `!list-agents` should show only the arbiter and that desk's worker. 📸 `06-membership.png`
- In `samepage-desk-claude`: `@samepage-claude use read_context on the room samepage-desk-codex and quote its last message`. Expected: refused, because it isn't a member. 📸 `07-cross-desk-refused.png`
- The audit trail: `@samepage-arbiter history <case>` lists `answer_sealed` ×2 before `revealed`.

## 8. Human approval → PR → retest (Gate 0, item 3, and the demo)

`@samepage-arbiter approve <case> spec is the source of truth`

Expected: "Recorded…", then a brief in `samepage-fix`; the fixer opens a PR on `samepage/<case>`; the arbiter checks the diff and posts "PR opened… Retesting"; a retest card shows "x/N before → N/N after" and RESOLVED. **You** merge the PR on GitHub.

📸 `08-approval.png`, `09-fix-room.png`, `10-pr.png`, `11-retest.png`

## 9. Record a real evaluation

1. `make demo-reset DOCS=…`, then commit and push, so the drift is back on `main`.
2. In the room: `@samepage-arbiter patrol full` asks 36 questions, in 6 batches per desk. This takes several minutes.
3. `make eval` scores the recorded answers into `reports/eval-*.md`. Copy that table into the README **exactly**.
4. Held-out H1: `uv run samepage holdout-branch --repo $SAMEPAGE_DOCS_REPO_DIR`, then `git -C … push -u origin holdout/h1`, then in the room `@samepage-arbiter patrol holdout` (asks the 6 H1 questions on `holdout/h1`), then `make eval-holdout`. Never merge `holdout/h1`.
5. While you're there, check that a 6-question batch reply fits in one Mattermost post (ADR 0003 caveat).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `register` returns 401 | Wrong URL (the Gateway, not the bridge) or wrong key |
| Workers never answer | The arbiter's owner differs from the workers' (bootstrap key used), or the workers' addressing isn't `owner-agents` |
| `can't approve` / `Only an approver can` | Add your username (or the sender id from the arbiter's log) to `SAMEPAGE_APPROVERS`. Owners of the losing docs can only approve. |
| Desk replies are ignored ("ignored a message in …'s room" in the log) | Switch reports agent senders differently than assumed: check `docs/evidence/phase0-raw-frames.jsonl`, or set `SAMEPAGE_STRICT_SENDER=false` |
| "cannot check the diff" | `GITHUB_TOKEN` / `GITHUB_DEMO_REPO` not set |
| Quotes fail verification | The engine's clone and the workers' clone are on different refs: check `SAMEPAGE_DOCS_REPO_DIR` and `git fetch` |

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

Create a **fine-grained token** (GitHub → Settings → Developer settings → Fine-grained tokens) with access to **only** `juniper-desk-docs` and **Contents: Read** and **Pull requests: Read**. The engine only reads PRs. Put it in `.env`:

```
GITHUB_TOKEN=<token>
GITHUB_DEMO_REPO=<you>/juniper-desk-docs
SAMEPAGE_DOCS_REPO_DIR=/absolute/path/to/juniper-desk-docs
```

The fixer agent opens PRs with the GitHub CLI signed in on this Mac: `gh auth login` (HTTPS), then `gh auth setup-git`.

## 3. Switch Console and its local server

1. Install Switch Console: https://github.com/sandbox-quantum/switch/releases/latest (`switch-console-arm64.dmg` on Apple Silicon).
2. **How do you want to run Switch? → On this computer**, with Mattermost on (Docker Desktop running). Wait until the local server shows **Running**. If it later says "isn't running", click **Start**.
3. **Settings → Agent providers:** Claude Code and Codex installed and signed in.
4. **Home → Messaging apps → Mattermost:** link it to yourself.

## 4. Register the arbiter (one command)

```sh
uv run samepage connect
```

It finds the server Console runs, signs in with the admin credentials Console generated, mints a personal registration key (so the arbiter has the same owner as the workers, ADR 0001 V5/V6), registers `samepage-arbiter`, and writes `SWITCH_API_URL`, `SWITCH_AGENT_ID` and `SWITCH_AGENT_API_KEY` into `.env`. Nothing secret is printed. Then set who may rule:

```sh
echo 'SAMEPAGE_APPROVERS=<your Mattermost username>' >> .env
```

## 5. Create the agents and rooms from the template

Console → **Templates → Import template** → choose `switch/samepage.template.yaml` → **Use template** → **Docs repository URL** `https://github.com/<you>/juniper-desk-docs`, **Docs repository (owner/name)** `<you>/juniper-desk-docs`, **Messaging app** Mattermost → **Create all**.

It creates `samepage-claude`, `samepage-codex`, `samepage-fixer` and five rooms, and adds the existing `samepage-arbiter` to its four rooms. **Gate 0, item 1:** the `samepage-smoke` kickoff makes both workers say hello (`docs/evidence/gate0-smoke-both-workers.png`).

## 6. Wire the arbiter to the rooms and start it

```sh
uv run samepage wire-rooms   # writes SAMEPAGE_ASK_ROOM, SAMEPAGE_FIX_ROOM, SAMEPAGE_DESKS into .env
make arbiter                 # leave it running; one log line per message Switch delivers
```

## 7. Sealed independence (Gate 0, item 2)

In **samepage-ask** (no @mention needed there): `ask Does the Starter plan include single sign-on?`

Expected: the "asking 2 agents separately" message; one batch request in each desk; each worker replies with a JSON block; one card in the ask room with both answers revealed together.

📸 `03-desk-claude.png`, `04-desk-codex.png`, `05-card.png`

Isolation checks:
- In each desk, `!list-agents` should show only the arbiter and that desk's worker. 📸 `06-membership.png`
- In `samepage-desk-claude`: `@samepage-claude use read_context on the room samepage-desk-codex and quote its last message`. Expected: refused, because it isn't a member. 📸 `07-cross-desk-refused.png`
- The audit trail: `history <case>` lists `answer_sealed` ×2 before `revealed`.

## 8. Human approval → PR → retest (Gate 0, item 3, and the demo)

`approve <case> spec is the source of truth`

Expected: "Recorded…", then a brief in `samepage-fix`; the fixer opens a PR on `samepage/<case>`; the arbiter checks the diff and posts "PR opened… Retesting"; a retest card shows "x/N before → N/N after" and RESOLVED, followed by the resolution receipt (`receipt <case>` shows it again). **You** merge the PR on GitHub.

📸 `08-approval.png`, `09-fix-room.png`, `10-pr.png`, `11-retest.png`

## 9. Record a real evaluation

1. `make demo-reset DOCS=…`, then commit and push, so the drift is back on `main`.
2. In samepage-ask: `patrol full` asks 36 questions, in 6 batches per desk. This takes several minutes.
3. `make eval` scores the recorded answers into `reports/eval-*.md`. Copy that table into the README **exactly**.
4. Held-out H1: `uv run samepage holdout-branch --repo $SAMEPAGE_DOCS_REPO_DIR`, then `git -C … push -u origin holdout/h1`, then in samepage-ask `patrol holdout` (asks the 6 H1 questions on `holdout/h1`), then `make eval-holdout`. Never merge `holdout/h1`.
5. While you're there, check that a 6-question batch reply fits in one Mattermost post (ADR 0003 caveat).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `connect` can't find the server | Start the local server in Switch Console first |
| Your message gets no reaction | It must be in samepage-ask (the arbiter isn't in samepage-smoke), and start with a command word or a real @mention |
| Workers never answer | The arbiter's owner differs from the workers' (bootstrap key used), or the workers' addressing isn't `owner-agents` |
| `can't approve` / `Only an approver can` | Add your username (or the sender id from the arbiter's log) to `SAMEPAGE_APPROVERS`. Owners of the losing docs can only approve. |
| Desk replies are ignored ("ignored a message in …'s room" in the log) | Switch reports agent senders differently than assumed: check `reports/frames.jsonl` (raw frames), or set `SAMEPAGE_STRICT_SENDER=false` |
| "cannot check the diff" | `GITHUB_TOKEN` / `GITHUB_DEMO_REPO` not set |
| Quotes fail verification | The engine's clone and the workers' clone are on different refs: check `SAMEPAGE_DOCS_REPO_DIR` and `git fetch` |

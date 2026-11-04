# Phase 0 runbook: the live part of Gate 0

**Who:** you, on your Mac (Apple Silicon). **Time:** about 60–90 minutes, most of it installs and sign-ins.
**Why it's on you:** Claude Code and Codex must run signed in to your accounts on your machine, and Switch Console is a desktop app.

Each step says what to capture. Put screenshots in `docs/evidence/` using the file names shown.

## 0. Prerequisites (check first)

```sh
node -v        # must be v20 or later. If missing: brew install node
docker info    # optional, only for the built-in Mattermost. Docker Desktop must be running.
codex --version
claude --version   # if missing, Switch Console can install it, but you must sign in yourself
uv --version       # if missing: brew install uv
```

## 1. Install Switch Console

Download the Apple Silicon build from https://github.com/sandbox-quantum/switch/releases/latest (`switch-console-arm64.dmg`) and open it.

## 2. Add a server

In the **Setting up Switch** checklist: **Add a server → Run a server on this computer**. Leave **Also run Mattermost** on, which needs Docker running. Wait for **Running locally** at the top of the sidebar.

## 3. Providers and your account

- **Set up agent providers:** make sure both **Claude Code** and **Codex** show as installed and signed in.
- **Home → Messaging apps → Mattermost → Link → This is me.** Without this, your agents will not recognise you.

## 4. Get the two values the arbiter needs

1. **The API (bridge) URL.** It's on the server's page in Console. Check it with `curl <url>/health`, which should return 200. A 401 means the right host but the wrong path. The Gateway URL is a *different* address.
2. **A personal registration key** minted by **you**: Gateway → API keys → create, labelled `samepage-arbiter`. Do **not** use the server's bootstrap token. It would make the arbiter belong to a different owner, and the workers would ignore it (ADR 0001, V6).

> Not verified: the exact Gateway menu wording. The endpoint behind it is `POST /api-keys`. If you can't find it, tell me what you see and I'll adjust.

## 5. Register the arbiter, then create the rooms

```sh
cd samepage
cp .env.example .env      # then set SWITCH_API_URL and SWITCH_REGISTRATION_TOKEN
uv run --with httpx python spike/arbiter_spike.py health
uv run --with httpx python spike/arbiter_spike.py register   # writes the agent id and key into .env
```

Then in Console: **Templates → Use/paste a template →** paste `switch/phase0-spike.template.yaml` **→ Create**.

📸 `docs/evidence/01-template-created.png`: the created agents and rooms.

**Gate 0, item 1:** the `samepage-smoke` room's kickoff asks both workers to say hello.
📸 `docs/evidence/02-smoke-two-agents.png`: both replies in the one room.

## 6. Start the arbiter

```sh
uv run --with httpx python spike/arbiter_spike.py rooms      # note the ids of the ask room and both desks
uv run --with httpx python spike/arbiter_spike.py run \
  --ask <samepage-ask id> \
  --desk samepage-claude=<samepage-desk-claude id> \
  --desk samepage-codex=<samepage-desk-codex id>
```

Leave it running. If it prints `post failed 404 ... Agent client not running`, stop and send me the output. That is open question U1, and there is a fallback.

## 7. Sealed independence (Gate 0, item 2)

In **samepage-ask** in Mattermost, type (and don't end the line with a period right after a name):

```
@samepage-arbiter ask Is single sign-on available on the Starter plan?
```

Expected: the arbiter says it asked 2 agents separately. Each desk gets the question, each worker answers **only from its own desk's document**, and the arbiter then posts both answers together. They should **differ**: desk A's FAQ says "all plans" and desk B's spec says "Enterprise only".

📸 `03-desk-claude.png`, `04-desk-codex.png`, `05-ask-reveal.png`

Two more checks:

- In each desk, type `!list-agents`. Each desk should list only the arbiter and its own worker.
  📸 `06-desk-membership.png`
- In **samepage-desk-claude**, type `@samepage-claude use read_context to read the room named samepage-desk-codex and quote its last message`. Expected: Switch refuses because it isn't a member.
  📸 `07-cross-desk-refused.png`

## 8. Human approval (Gate 0, item 3)

In **samepage-ask**:

```
@samepage-arbiter approve <case-id> spec is the source of truth
```

Expected reply: `Recorded: <you> chose approve on case <id>`.
📸 `08-approval.png`

## 9. Check the evidence

```sh
uv run --with httpx python spike/arbiter_spike.py verify
```

This should print `1 revealed case(s) checked; 0 problem(s)`. Then send me:

- `docs/evidence/phase0-events.jsonl`: the dispatch, seal, reveal and decision records
- `docs/evidence/phase0-raw-frames.jsonl`: the real protocol frames, for the Slice D contract tests
- the screenshots, and anything that went differently from "Expected"

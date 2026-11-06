# ADR 0001: How SamePage plugs into Switch

- **Status:** Accepted after the live run on 2026-11-06 (see the last section).
- **Date:** 2026-11-03
- **Roles:** Agent Engineer (author), Architect, Security Engineer
- **Switch version read:** `sandbox-quantum/switch` at commit `7e1316f767ee341ea4b91d7720330907c42a65b6` (2026-11-04 03:24 UTC)

## Context

SamePage needs three things from Switch: a way for our own Python service to be a room participant, a way to keep the two worker agents' first answers independent, and a way for a human to rule on a case from the chat. The brief lists candidate mechanisms and asks us to verify which ones Switch actually supports.

## What we verified, and where

Paths are in the Switch repo. "Docs" means `docs/official/`, published at https://docs.switchagents.ai/flintai/switch.

| # | Fact | Evidence |
|---|---|---|
| V1 | A custom service can be a room participant. It registers once with `POST /agents` (a full integration profile with a free-text `connector_type`), then streams events over SSE and acts over HTTP. | Docs `internals/agent-protocol.md` ("Writing a client"); `core/switch_core/bridges/agent/api/handlers.py` (`register_agent_endpoint`, `@router.post("")`); `bridges/agent/api/schemas.py` (`RegisterAgentRequest`) |
| V2 | The stream is `GET /agents/{id}/events` with a client-generated, reused `connection_id`. The first frame is `connection_state`. Heartbeat is `POST .../connection/beat` every 2 s, with a 6 s TTL. A 404 or 409 on a beat means reopen the stream, not back off. | Docs `internals/agent-protocol.md` ("Connections", "The heartbeat") |
| V3 | A message event carries `addressed`, `sender`, `sender_name`, `message_id`, `body`, `timestamp`, `thread_id`. | Docs `internals/agent-protocol.md` ("The event catalog") |
| V4 | **Membership is the read boundary.** An agent can read only rooms it belongs to. `read_context` on another room is refused. | `core/switch_core/bridges/agent/operations/definitions.py`, `read_context` docstring; enforced by `require_room_member` in `bridges/agent/protocol/agent_core.py` `read_context`. The README also says an agent only sees the rooms it belongs to. |
| V5 | New agents default to an addressing policy that admits **the owner and the owner's other agents**. The module docstring names our exact pattern: "the manager dispatching a worker is the owner acting through a program." | `core/switch_core/addressing.py` (module docstring, `default_agent_policy`); `agent_core.register_agent` |
| V6 | The registration token decides the owner. A personal key (minted in the Gateway under API keys) resolves to the person who minted it. The deployment **bootstrap** key resolves to a separate non-admin account. | `bridges/agent/api/handlers.py` `_resolve_registration_user_id`; `bridges/agent/registration_bootstrap.py` `resolve_registration_owner_id`; `gateway/api_keys.py` `create_api_key` (mounted at `/api-keys`) |
| V7 | Addressing is computed from `@name` text. `send_targeted_message` only prepends `@name` to the body. | `bridges/agent/protocol/agent_core.py` `send_targeted_message` docstring; docs `using/mention-and-message.md` |
| V8 | **Custom `!` commands are not forwarded to agents.** An unknown command gets an "Unknown command" notice from Switch, and agents stay silent. Mattermost has no Switch slash commands. | `core/switch_core/bridges/agent/commands.py` `dispatch_command` / `dispatch_admin_command`; docs `resources/room-commands.md` ("Slash commands" table) |
| V9 | Templates can declare agents (provider `claude` / `codex`), a room group with several rooms, per-room documents (`docs:`), private channels, links between rooms, and per-room kickoffs. A room may list agents that already exist on the server. | `docs/TEMPLATES.md` ("The agent block", "The room block", "Groups"); `examples/agent-templates/triage-pair.template.yaml` |
| V10 | Correction to the brief: Switch Console now runs a local server **without Docker**. Docker is needed only for the optional built-in Mattermost. | Docs `getting-started/add-a-server.md` ("Run a server on this computer") |
| V11 | Switch Console requires Node.js 20+ on the computer that runs the agents, and an account for each provider (Claude Code, Codex). | Docs `getting-started/index.md` |

## Decision

### 1. SamePage is its own room participant (the "SamePage Arbiter")

The Engine registers as the agent `samepage-arbiter` with `POST /agents` (V1). It holds one `scope=all` SSE connection covering the ask room and both desk rooms (V2), and posts with `POST /agents/{id}/message`. This puts Switch on the critical path. Without the room, nothing reaches the workers and no ruling reaches the Engine.

It must be registered with **the human owner's personal registration key**, not the bootstrap key. Otherwise it has a different owner from the workers, and the default addressing policy would not let it wake them (V5, V6).

### 2. Sealed independence uses mechanism (a): one private desk room per worker

```
samepage-ask          you + arbiter              questions in, sealed answers revealed together
samepage-desk-claude  you + arbiter + Claude Code  only this worker answers here
samepage-desk-codex   you + arbiter + Codex        only this worker answers here
```

- The arbiter posts `@<worker> [case <id>] <question>` into each desk. Workers use `addressing: owner-agents`, so the arbiter can wake them (V5, V7).
- Neither worker is a member of the other desk or of the ask room. Switch refuses those reads (V4), so a worker cannot see the other's answer, even after the reveal.
- The arbiter records each **first** answer with a SHA-256 hash and a timestamp. It reveals the answers in the ask room only once every desk has replied. `spike/sealed.py::verify_ordering` checks the log: every seal falls after its dispatch and before its reveal, and the revealed hashes equal the sealed hashes.
- The whole topology is declared in one template (V9): `switch/phase0-spike.template.yaml`. The different-subsets test uses per-room `docs:`. Desk A holds a drifted FAQ ("SSO on all plans") and desk B holds the spec ("Enterprise only"), so a correct run must produce **different** answers.

**Rejected alternatives:**

- **(b) Workers submit to the Engine over HTTP before posting.** Coding agents would need a custom tool or MCP server, and sealing would rest on the agent obeying an instruction rather than on a server-side rule. It also moves the work out of the room, which weakens "Switch is central."
- **(c) Addressing as an isolation tool.** Addressing controls who may *wake* an agent, not what it can *read*. Docs `using/mention-and-message.md`: "Addressing narrows who acts on a message, not who reads it." On its own it does not seal anything.

### 3. Human rulings are addressed messages, not slash commands

Because of V8, the brief's `/approve <id>` and `/samepage history <topic>` cannot work as written. The room syntax becomes:

```
@samepage-arbiter ask <question>
@samepage-arbiter approve <case-id> [reason]
@samepage-arbiter reject  <case-id> [reason]
@samepage-arbiter history <topic>        (Slice E)
```

The arbiter receives these as `message` events with `addressed: true` and records `sender`, `sender_name`, `message_id` and time (V3). For Phase 0, only the owner can address the arbiter, which is the default policy. For teammates to ask questions in Phase 3, the arbiter's addressing has to be widened to `anyone`. At that point, *approval* authority must be checked in Engine code against a configured owner list, not left to Switch. This is a Security Engineer follow-up.

### 4. Gate 0 item 1 gets its own smoke room

The sealed design keeps the workers apart. Gate 0 still asks for both agents answering in one room, so the template adds `samepage-smoke`, with both workers and a kickoff that mentions both. Nothing else uses it.

## Still unverified (needs the live run)

| # | Question | How the runbook settles it |
|---|---|---|
| U1 | Does `POST /agents/{id}/message` from an `always_on` custom agent succeed while its stream is open? `agent_core.send_message` raises "Agent client not running" if no server-side client exists for the agent. | Step 6 of the runbook. Fallback: `connect_to_room`, then the `send_targeted_message` op. |
| U2 | Does an `@worker` mention inside an agent-posted message wake a Console-run Claude Code or Codex session in that room? | Step 7. Expected yes, by V7. |
| U3 | Do Claude Code and Codex reliably read room `docs:` with their Switch tools, and reply with only the JSON block? | Step 7, read the desk rooms |
| U4 | Does the template run with `samepage-arbiter` listed as an existing agent in three rooms, with a group, private channels and `docs:`? | Step 5 |
| U5 | Exact `connection_state` fields and `message` payloads on this server version (for the Slice D contract tests) | `docs/evidence/phase0-raw-frames.jsonl` from the live run |

## Consequences

- Switch is load-bearing: rooms, membership-based sealing, addressing and rulings all live there.
- Users see three or four channels instead of one. We present the desks as glass-walled offices: humans can watch every desk live, but the agents cannot see each other's.
- Every worker runs on the owner's machine through Switch Console, so the demo machine needs Node 20+, a signed-in Claude Code, and a signed-in Codex.
- We depend on the agent protocol revision on this server. The Slice D contract tests will be built from the recorded raw frames (U5), not from memory.

## Addendum (2026-11-05)

- **Verified since:** template agents accept `repo:` (Console clones it into the agent's directory), `connections:` (for example GitHub write), and `allow_existing:` (`docs/TEMPLATES.md`, "The agent block"). These drive ADR 0003.
- **Correction:** `docs/TEMPLATES.md` says a *template* agent's `addressing` defaults to `owner`, while `addressing.py` gives newly registered agents `owner-agents`. Our template sets `owner-agents` explicitly on every agent, so the difference doesn't matter here.
- **Rulings** gained `override <case> <file>`. Owners of the losing sources may approve; override and reject need an approver (ADR 0004).
- **Smoke room:** the real template (`switch/samepage.template.yaml`) includes `samepage-smoke` for Gate 0 item 1. The Phase 0 spike files moved to `spike/`.
- **U4 partly settled offline:** Switch's own code accepts `switch/samepage.template.yaml`. `template_lint.lint_template` reports no errors or warnings. `agent_templates.agent_slots` reads 3 agent slots (the fixer with a GitHub write grant scoped to `{docs_repo_name}`). `room_document` plus `rooms_yaml.GroupTemplateDocument` read 5 rooms (3 private) and 3 links. Provisioning itself (machines, sign-ins, the existing `samepage-arbiter`) still needs the live run.
- **Still open:** U1–U3 and U5, plus the provisioning half of U4. Nothing live has been run.

## Live run (2026-11-06, Switch Console 0.40.1, server 0.31.0, agent protocol 9)

Status changes to **Accepted**. On the human's Mac, with real Claude Code and Codex sessions run by Console:

| # | Result | Evidence |
|---|---|---|
| U1 | **Yes.** The `always_on` arbiter posts with `POST /agents/{id}/message` while its stream is open. | Cards in samepage-ask; `docs/evidence/live-c1-*.png` |
| U2 | **Yes.** `@samepage-claude [batch …]` posted by the arbiter wakes the Console-run session in that desk ("Starting a session…", then the answer). | `reports/frames.jsonl` on the demo machine; `tests/fixtures/live/` |
| U3 | **Yes**, both workers replied with `[batch <id>]` and a JSON block that parsed first time. Claude Code adds supporting claims, including the conflicting FAQ lines; Codex gives one claim. | `tests/fixtures/live/c1-sso-2026-11-06.jsonl` |
| U4 | **Yes**, with one change: Console's GitHub connector needs the server to have an https address, so the fixer uses the local `gh` sign-in instead (template `connections:` removed). The existing `samepage-arbiter` was accepted in all four rooms. | `docs/evidence/gate0-smoke-both-workers.png` |
| U5 | Message frames match `MessagePayload`. A human is `sender_name: "user"`, sender `@switch-mattermost-…`; an agent is `sender_name: "<agent name>"`, sender `@switch-agent-…:localhost`. `sender_kind` was null on this version. A command typed **without** the @mention arrives with `addressed: false`, so the ask room now accepts a leading command word too. | Raw frames; `test_live_replies.py` |

Two engine bugs found by real answers and fixed with the real replies as a test: a quote wrapped across lines ("not available⏎on the Starter …") was read as two clauses, and "not available (Enterprise only)" was read as yes.

Full live loop on C1: ask → sealed answers → SOURCE_CONFLICT (agents agree, website and sales FAQs disagree) → `approve` → fixer opened https://github.com/SCVaitla/juniper-desk-docs/pull/1 (2 files, 4 lines each way, diff guard passed) → retest 0/4 → 4/4 → RESOLVED.

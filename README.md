# SamePage

**SamePage turns disagreements between AI agents into an investigation, a human decision, and a verified fix.**

> Status: **Phase 0 (discovery spike).** Nothing below is a working product yet. See `docs/adr/0001-switch-integration.md` for what has been verified about Switch, and `docs/PHASE0_RUNBOOK.md` for the live checks still to run.

Built for the Flip the Switch hackathon (Best Business Workflow). Juniper Desk, the company in every example, is fictional.

## How Switch is used (planned, per ADR 0001)

- The SamePage Arbiter is a Switch **agent** of its own. It speaks the agent protocol: SSE in, HTTP out.
- Claude Code and Codex each answer in a **private desk room**. Switch only lets an agent read rooms it belongs to, so neither can see the other's answer. The arbiter reveals both together.
- Humans rule in the room: `@samepage-arbiter approve <case>`.
- The rooms, agents and their instructions are declared in a Switch **template** (`switch/`).

## Repo layout (so far)

| Path | What |
|---|---|
| `CLAUDE.md` | The build brief: the rules every coding session follows |
| `docs/adr/` | Architecture decisions |
| `docs/PHASE0_RUNBOOK.md` | Steps to run the Gate 0 checks on a real Switch server |
| `docs/evidence/` | Screenshots and logs proving each gate |
| `switch/phase0-spike.template.yaml` | Switch template: the smoke room, the ask room and two private desks |
| `spike/` | Throwaway Phase 0 arbiter: protocol client and sealing logic, with tests |
| `samepage/`, `corpus/`, `eval/`, `tests/` | Empty until Phases 2–3 |

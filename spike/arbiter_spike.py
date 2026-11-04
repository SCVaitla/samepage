"""Phase 0 spike: a minimal SamePage Arbiter speaking the Switch agent protocol.

Protocol facts used here (sandbox-quantum/switch @ 7e1316f, docs/official/internals/agent-protocol.md):
  * Register once: POST /agents with a registration token -> {id, api_key} (key shown once).
  * Down: GET /agents/{id}/events (SSE). First frame is `connection_state`.
  * Heartbeat: POST /agents/{id}/connection/beat every 2 s (TTL 6 s). 404/409 => reopen stream.
  * Up: POST /agents/{id}/message {room_id, content}; ops at POST /agents/{id}/ops/{name}.
  * Addressing is computed from `@name` text (send_targeted_message only prepends `@name`).

Usage (reads .env in the repo root):
  python spike/arbiter_spike.py health
  python spike/arbiter_spike.py register          # appends SWITCH_AGENT_ID / _API_KEY to .env
  python spike/arbiter_spike.py rooms             # list rooms the arbiter belongs to, with ids
  python spike/arbiter_spike.py run --ask ROOM_ID --desk samepage-claude=ROOM_ID --desk samepage-codex=ROOM_ID
  python spike/arbiter_spike.py verify            # checks the ordering proof in the evidence log
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from sealed import Arbiter, Desk, Post, Record, verify_ordering  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence" / "phase0-events.jsonl"
RAW_FRAMES = ROOT / "docs" / "evidence" / "phase0-raw-frames.jsonl"
TIMEOUT = httpx.Timeout(10.0, read=None)  # the SSE read waits indefinitely; keepalives every 15 s


# ---- config ----------------------------------------------------------------

def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"Missing {name}. Set it in .env (see .env.example).")
    return value


def base() -> str:
    return need("SWITCH_API_URL").rstrip("/")


def agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {need('SWITCH_AGENT_API_KEY')}"}


# ---- SSE parsing (pure, unit tested) ----------------------------------------

def parse_sse(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yield {'id', 'event', 'data'} per SSE frame. Comment lines (keepalives) are skipped."""
    frame: dict[str, Any] = {"id": None, "event": None, "data": []}
    for line in lines:
        if line == "":
            if frame["data"]:
                yield {"id": frame["id"], "event": frame["event"], "data": "\n".join(frame["data"])}
            frame = {"id": None, "event": None, "data": []}
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "data":
                frame["data"].append(value)
            elif field in ("id", "event"):
                frame[field] = value


# ---- commands ----------------------------------------------------------------

def cmd_health(_: argparse.Namespace) -> None:
    r = httpx.get(f"{base()}/health", timeout=10)
    print(r.status_code, r.text[:300])


def cmd_register(args: argparse.Namespace) -> None:
    body = {
        "name": args.name,
        "description": "SamePage Arbiter: collects sealed answers and records human rulings",
        "display_name": "SamePage",
        "connector_type": "SamePage Arbiter",
        "integration_profile": {
            "connection_model": "always_on",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }
    r = httpx.post(f"{base()}/agents", json=body, timeout=15,
                   headers={"Authorization": f"Bearer {need('SWITCH_REGISTRATION_TOKEN')}"})
    if r.status_code != 200:
        sys.exit(f"Register failed: {r.status_code} {r.text[:500]}")
    data = r.json()
    with (ROOT / ".env").open("a") as f:  # .env is gitignored; the key is returned only once
        f.write(f"\nSWITCH_AGENT_ID={data['id']}\nSWITCH_AGENT_API_KEY={data['api_key']}\n")
    print(f"Registered {args.name} as {data['id']}. API key written to .env (not printed).")


def op(name: str, args: dict[str, Any], connection_id: str | None = None) -> Any:
    headers = agent_headers()
    if connection_id:
        headers["X-Switch-Connection-Id"] = connection_id
    r = httpx.post(f"{base()}/agents/{need('SWITCH_AGENT_ID')}/ops/{name}",
                   json=args, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()["result"]


def cmd_rooms(_: argparse.Namespace) -> None:
    print(json.dumps(op("list_rooms", {}), indent=2)[:4000])


def post(room_id: str, content: str) -> None:
    for attempt in range(3):  # bounded retry with backoff
        try:
            r = httpx.post(f"{base()}/agents/{need('SWITCH_AGENT_ID')}/message",
                           json={"room_id": room_id, "content": content},
                           headers=agent_headers(), timeout=15)
            if r.status_code == 200:
                return
            print(f"post failed {r.status_code}: {r.text[:300]}", file=sys.stderr)
        except httpx.HTTPError as exc:
            print(f"post error: {exc}", file=sys.stderr)
        time.sleep(2 ** attempt)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_run(args: argparse.Namespace) -> None:
    desks = []
    for spec in args.desk:
        worker, _, room = spec.partition("=")
        desks.append(Desk(worker=worker, room_id=room))
    arbiter = Arbiter(ask_room=args.ask, desks=desks, self_name=os.environ.get("SWITCH_AGENT_NAME", "samepage-arbiter"))
    agent_id = need("SWITCH_AGENT_ID")
    connection_id = str(uuid.uuid4())  # reused across reconnects
    cursor = {"value": 0}
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.is_set():
            try:
                httpx.post(f"{base()}/agents/{agent_id}/connection/beat",
                           json={"connection_id": connection_id, "cursor": cursor["value"]},
                           headers=agent_headers(), timeout=5)
            except httpx.HTTPError:
                pass  # a lapsed beat surfaces as an `evicted` frame; the outer loop reopens
            stop.wait(2)

    rooms = ",".join([args.ask, *[d.room_id for d in desks]])
    params = {"connection_id": connection_id, "scope": "all", "filter": "all",
              "start_from": "head", "rooms": rooms, "client": "samepage-spike", "client_version": "0.0.1"}
    threading.Thread(target=heartbeat, daemon=True).start()
    print(f"Listening as {agent_id}. Ask room {args.ask}; desks {[d.worker for d in desks]}. Ctrl-C to stop.")
    try:
        while True:
            headers = {**agent_headers(), "Accept": "text/event-stream"}
            if cursor["value"]:
                headers["Last-Event-ID"] = str(cursor["value"])
            try:
                with httpx.stream("GET", f"{base()}/agents/{agent_id}/events",
                                  params=params, headers=headers, timeout=TIMEOUT) as resp:
                    if resp.status_code != 200:
                        print(f"stream open failed {resp.status_code}: {resp.read()[:300]!r}", file=sys.stderr)
                        time.sleep(3)
                        continue
                    for frame in parse_sse(resp.iter_lines()):
                        event = json.loads(frame["data"])
                        append_jsonl(RAW_FRAMES, {"sse_event": frame["event"], "data": event})
                        if frame["id"]:
                            cursor["value"] = int(frame["id"])
                        if frame["event"] == "evicted":
                            break
                        for action in arbiter.on_event(event):
                            if isinstance(action, Record):
                                append_jsonl(EVIDENCE, {"kind": action.kind, **action.data})
                                print(f"[{action.kind}] {action.data.get('case_id')}")
                            elif isinstance(action, Post):
                                post(action.room_id, action.body)
            except httpx.HTTPError as exc:
                print(f"stream error: {exc}; reopening", file=sys.stderr)
                time.sleep(2)
    except KeyboardInterrupt:
        stop.set()


def cmd_verify(_: argparse.Namespace) -> None:
    if not EVIDENCE.exists():
        sys.exit(f"No evidence yet at {EVIDENCE}. Run `run` and ask a question first.")
    rows =[json.loads(line) for line in EVIDENCE.read_text().splitlines() if line.strip()]
    problems = verify_ordering(rows)
    cases = {r["case_id"] for r in rows if r["kind"] == "revealed"}
    print(f"{len(cases)} revealed case(s) checked; {len(problems)} problem(s)")
    for p in problems:
        print(" -", p)
    sys.exit(1 if problems else 0)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)
    sub.add_parser("health").set_defaults(fn=cmd_health)
    reg = sub.add_parser("register")
    reg.add_argument("--name", default=os.environ.get("SWITCH_AGENT_NAME", "samepage-arbiter"))
    reg.set_defaults(fn=cmd_register)
    sub.add_parser("rooms").set_defaults(fn=cmd_rooms)
    run = sub.add_parser("run")
    run.add_argument("--ask", required=True, help="room id of samepage-ask")
    run.add_argument("--desk", action="append", required=True, help="worker-name=desk-room-id (repeat)")
    run.set_defaults(fn=cmd_run)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

"""Minimal async client for the Switch agent protocol (SSE in, HTTP out).

Verified against sandbox-quantum/switch @ 7e1316f, docs/official/internals/agent-protocol.md:
  register  POST /agents                          (registration token -> {id, api_key}, key shown once)
  stream    GET  /agents/{id}/events              (SSE; first frame `connection_state`; reuse connection_id)
  beat      POST /agents/{id}/connection/beat     (every 2 s, TTL 6 s; 404/409 => reopen the stream)
  post      POST /agents/{id}/message             {room_id, content}
  ops       POST /agents/{id}/ops/{name}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx

log = logging.getLogger("samepage.switch")


def parse_sse(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse complete SSE text into frames {'id', 'event', 'data'}. Comment lines are keepalives."""
    frames: list[dict[str, Any]] = []
    frame: dict[str, Any] = {"id": None, "event": None, "data": []}
    for line in lines:
        if line == "":
            if frame["data"]:
                frames.append({"id": frame["id"], "event": frame["event"], "data": "\n".join(frame["data"])})
            frame = {"id": None, "event": None, "data": []}
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "data":
                frame["data"].append(value)
            elif field in ("id", "event"):
                frame[field] = value
    return frames


class SwitchClient:
    def __init__(self, base_url: str, agent_id: str, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.agent_id = agent_id
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=None))
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.connection_id = str(uuid.uuid4())  # reused across reconnects, per the protocol
        self.cursor = 0

    async def post(self, room_id: str, content: str, attempts: int = 3) -> None:
        """Post a message. Bounded retries with exponential backoff."""
        url = f"{self.base}/agents/{self.agent_id}/message"
        for attempt in range(attempts):
            try:
                r = await self.http.post(
                    url, json={"room_id": room_id, "content": content}, headers=self.headers, timeout=15
                )
                if r.status_code == 200:
                    return
                log.warning("post failed %s: %s", r.status_code, r.text[:300])
                if r.status_code < 500 and r.status_code != 429:
                    break  # a 4xx will not fix itself
            except httpx.HTTPError as exc:
                log.warning("post error: %s", exc)
            await asyncio.sleep(2**attempt)
        raise RuntimeError(f"could not post to room {room_id}")

    async def op(self, name: str, args: dict[str, Any]) -> Any:
        r = await self.http.post(
            f"{self.base}/agents/{self.agent_id}/ops/{name}",
            json=args,
            headers={**self.headers, "X-Switch-Connection-Id": self.connection_id},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("result")

    async def _heartbeat(self, stop: asyncio.Event) -> None:
        url = f"{self.base}/agents/{self.agent_id}/connection/beat"
        while not stop.is_set():
            # A failed beat is not fatal: a lapsed lease shows up as an `evicted` frame and the stream reopens.
            with contextlib.suppress(httpx.HTTPError):
                await self.http.post(
                    url,
                    json={"connection_id": self.connection_id, "cursor": self.cursor},
                    headers=self.headers,
                    timeout=5,
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=2)

    async def events(self, rooms: list[str]) -> AsyncIterator[dict[str, Any]]:
        """Yield event envelopes forever, reconnecting with Last-Event-ID after drops."""
        params = {
            "connection_id": self.connection_id,
            "scope": "all",
            "filter": "all",
            "start_from": "head",
            "rooms": ",".join(rooms),
            "client": "samepage",
            "client_version": "0.1.0",
        }
        stop = asyncio.Event()
        beat = asyncio.create_task(self._heartbeat(stop))
        try:
            while True:
                headers = {**self.headers, "Accept": "text/event-stream"}
                if self.cursor:
                    headers["Last-Event-ID"] = str(self.cursor)
                try:
                    async with self.http.stream(
                        "GET", f"{self.base}/agents/{self.agent_id}/events", params=params, headers=headers
                    ) as resp:
                        if resp.status_code != 200:
                            log.warning("stream open failed %s", resp.status_code)
                            await asyncio.sleep(3)
                            continue
                        buffer: list[str] = []
                        async for line in resp.aiter_lines():
                            buffer.append(line)
                            if line != "":
                                continue
                            for frame in parse_sse(buffer):
                                if frame["id"]:
                                    self.cursor = int(frame["id"])
                                if frame["event"] == "evicted":
                                    raise ConnectionResetError("evicted")
                                yield json.loads(frame["data"])
                            buffer = []
                except (httpx.HTTPError, ConnectionResetError) as exc:
                    log.warning("stream dropped (%s); reopening", exc)
                    await asyncio.sleep(2)
        finally:
            stop.set()
            beat.cancel()

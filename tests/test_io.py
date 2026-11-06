"""I/O edges: HTTP API, Switch protocol client, GitHub client, reading the corpus at a git ref."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from samepage.api import create_app
from samepage.config import Settings
from samepage.corpus import Corpus
from samepage.github import GitHub
from samepage.switch_client import SwitchClient, parse_sse
from tests.helpers import CORPUS_DIR, claim


def api(tmp_path: Path) -> TestClient:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None, SAMEPAGE_CORPUS_DIR=str(CORPUS_DIR), SAMEPAGE_DB_PATH=str(tmp_path / "a.sqlite")
    )
    return TestClient(create_app(s))


def test_api_health_evaluate_limits_and_validation(tmp_path: Path) -> None:
    client = api(tmp_path)
    assert client.get("/healthz").json()["ok"] is True
    c = claim("product_spec.md", "Starter workspaces are limited to 5 seats", "5", "seats", "limit", "starter")
    raw = "```json\n" + json.dumps({"answer": "5", "claims": [c.model_dump()]}) + "\n```"
    pair = [{"agent": "a", "raw": raw}, {"agent": "b", "raw": raw}]
    body = {"question": "How many seats on Starter?", "answers": pair}
    r = client.post("/v1/evaluate", json=body)
    assert r.status_code == 200 and r.json()["outcome"] == "SOURCE_CONFLICT"
    assert "Blast radius" in r.json()["card"]
    assert client.post("/v1/evaluate", json={"question": "x", "answers": []}).status_code == 422
    big = client.post(
        "/v1/evaluate", content=b"{" + b" " * 200_000 + b"}", headers={"content-type": "application/json"}
    )
    assert big.status_code == 413
    assert client.get("/v1/trust").json() == []
    assert client.get("/v1/cases/NOTHEX!!/history").status_code == 422
    assert client.get("/v1/cases/abcdef12/history").json() == []


def test_parse_sse_frames() -> None:
    raw = [
        ": keepalive",
        "",
        "event: connection_state",
        'data: {"cursor": 0}',
        "",
        "id: 7",
        "event: message",
        'data: {"a":',
        "data: 1}",
        "",
    ]
    assert parse_sse(raw) == [
        {"id": None, "event": "connection_state", "data": '{"cursor": 0}'},
        {"id": "7", "event": "message", "data": '{"a":\n1}'},
    ]


def test_switch_client_posts_retries_streams_and_reconnects() -> None:
    calls: list[str] = []
    state = {"post": 0, "stream": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/message"):
            state["post"] += 1
            return httpx.Response(503 if state["post"] == 1 else 200, json={"ok": True})
        if request.url.path.endswith("/beat"):
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/ops/list_rooms"):
            return httpx.Response(200, json={"result": [{"id": "r1"}]})
        if request.url.path.endswith("/events"):
            state["stream"] += 1
            if state["stream"] == 1:
                assert "Last-Event-ID" not in request.headers
                return httpx.Response(
                    200,
                    text='event: connection_state\ndata: {"cursor":0}\n\n'
                    'id: 5\nevent: message\ndata: {"type":"message","n":1}\n\n'
                    'event: evicted\ndata: {"reason":"lease"}\n\n',
                )
            assert request.headers["Last-Event-ID"] == "5"
            return httpx.Response(200, text='id: 6\nevent: message\ndata: {"type":"message","n":2}\n\n')
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = SwitchClient("http://switch.test", "agent-1", "key", http)

    async def go() -> list[dict[str, object]]:
        await client.post("room", "hi")
        assert await client.op("list_rooms", {}) == [{"id": "r1"}]
        seen = []
        async for event in client.events(["room"]):
            seen.append(event)
            if len(seen) == 3:
                break
        return seen

    import samepage.switch_client as sc

    original = sc.asyncio.sleep

    async def no_sleep(_: float) -> None:
        await original(0)

    sc.asyncio.sleep = no_sleep  # type: ignore[assignment]
    try:
        events = asyncio.run(go())
    finally:
        sc.asyncio.sleep = original  # type: ignore[assignment]
    assert [e.get("n") for e in events] == [None, 1, 2]
    assert state["post"] == 2 and state["stream"] == 2


def test_switch_client_gives_up_on_4xx() -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="no")))
    client = SwitchClient("http://switch.test", "a", "k", http)
    with pytest.raises(RuntimeError, match="could not post"):
        asyncio.run(client.post("room", "hi", attempts=1))


def test_github_reads_pr_and_rejects_other_repos() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Accept"] == "application/vnd.github.diff":
            return httpx.Response(200, text="--- a/x\n+++ b/x\n")
        return httpx.Response(
            200, json={"head": {"ref": "samepage/abcdef12"}, "base": {"ref": "main"}, "state": "open", "merged": False}
        )

    gh = GitHub(
        "t", "acme/docs", httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    )
    pr = asyncio.run(gh.pull_request("see https://github.com/acme/docs/pull/7 thanks"))
    assert pr.number == 7 and pr.head_ref == "samepage/abcdef12" and not pr.merged and pr.diff.startswith("---")
    with pytest.raises(ValueError, match="only works on"):
        asyncio.run(gh.pull_request("https://github.com/evil/repo/pull/1"))
    with pytest.raises(ValueError, match="not a GitHub"):
        asyncio.run(gh.pull_request("https://example.com"))


def test_corpus_from_git_ref(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo = tmp_path / "docs"
    shutil.copytree(CORPUS_DIR, repo / "corpus")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "docs")
    c = Corpus.from_git(repo, "main", "corpus")
    assert set(c.files) == set(Corpus.from_dir(CORPUS_DIR).files)
    assert c.plans == ["starter", "pro", "enterprise"]
    with pytest.raises(ValueError, match="unsafe"):
        Corpus.from_git(repo, "main; rm -rf /")
    with pytest.raises(ValueError, match="unsafe"):
        Corpus.from_git(repo, "../../etc")

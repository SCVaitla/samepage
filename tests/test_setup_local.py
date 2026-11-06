"""`samepage connect` and `wire-rooms` against a fake local Switch server (httpx MockTransport)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from samepage.setup_local import SetupError, connect, parse_env, room_ids, set_env_values, wire_rooms


def fake_switch_dir(tmp_path: Path, port: int = 51234) -> Path:
    run = tmp_path / "switchdash" / "servers" / "local" / "run"
    run.mkdir(parents=True)
    (run / "switch-core.env").write_text(f"SERVER_PORT={port}\nGATEWAY_ADMIN_PASSWORD=pw123\nOTHER=x\n")
    return tmp_path / "switchdash"


def server(seen: list[httpx.Request], *, register_status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/gateway/auth/login":
            body = json.loads(request.content)
            assert body == {"email": "admin@switch.local", "password": "pw123"}
            return httpx.Response(
                200, json={"id": "u1"}, headers={"set-cookie": "switch_session=abc; Secure; HttpOnly"}
            )
        if path == "/gateway/api-keys":
            assert request.headers["cookie"] == "switch_session=abc"
            return httpx.Response(
                200, json={"id": "k1", "label": "samepage-arbiter", "key": "reg-key", "created_at": "t"}
            )
        if path == "/agents":
            assert request.headers["authorization"] == "Bearer reg-key"
            if register_status != 200:
                return httpx.Response(register_status, json={"detail": "name taken"})
            return httpx.Response(200, json={"id": "agent-42", "api_key": "agent-secret"})
        if path == "/agents/agent-42/ops/list_rooms":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"room_id": "r-ask", "name": "samepage-ask"},
                        {"room_id": "r-a", "name": "samepage-desk-claude"},
                        {"room_id": "r-b", "name": "samepage-desk-codex"},
                        {"room_id": "r-fix", "name": "samepage-fix"},
                        {"room_id": "r-x", "name": "Town Square"},
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_connect_signs_in_mints_a_personal_key_registers_and_writes_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# keep me\nSWITCH_API_URL=http://old\n# SWITCH_AGENT_ID=\nGITHUB_TOKEN=t\n")
    seen: list[httpx.Request] = []
    done = connect(fake_switch_dir(tmp_path), env, "samepage-arbiter", server(seen))
    assert done == {"url": "http://localhost:51234", "agent_id": "agent-42"}
    values = parse_env(env.read_text())
    assert values["SWITCH_API_URL"] == "http://localhost:51234"
    assert values["SWITCH_AGENT_ID"] == "agent-42" and values["SWITCH_AGENT_API_KEY"] == "agent-secret"
    assert values["GITHUB_TOKEN"] == "t" and "# keep me" in env.read_text()
    assert env.read_text().count("SWITCH_AGENT_ID=") == 1
    assert oct(os.stat(env).st_mode)[-3:] == "600"
    assert [r.url.path for r in seen] == ["/health", "/gateway/auth/login", "/gateway/api-keys", "/agents"]


def test_connect_explains_each_failure(tmp_path: Path) -> None:
    with pytest.raises(SetupError, match="No local Switch server"):
        connect(tmp_path / "nothing", tmp_path / ".env", "a", server([]))
    with pytest.raises(SetupError, match="may already exist"):
        connect(fake_switch_dir(tmp_path), tmp_path / ".env", "samepage-arbiter", server([], register_status=409))
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(SetupError, match="Click Start"):
        connect(tmp_path / "switchdash", tmp_path / ".env", "a", down)


def test_wire_rooms_writes_ids_and_names_missing_rooms(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    updates = wire_rooms("http://localhost:51234", "agent-42", "agent-secret", env, server([]))
    assert updates == {
        "SAMEPAGE_ASK_ROOM": "r-ask",
        "SAMEPAGE_FIX_ROOM": "r-fix",
        "SAMEPAGE_DESKS": "samepage-claude=r-a,samepage-codex=r-b",
    }
    assert parse_env(env.read_text())["SAMEPAGE_DESKS"] == "samepage-claude=r-a,samepage-codex=r-b"
    only_ask = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"result": [{"room_id": "r-ask", "name": "samepage-ask"}]})
        )
    )
    with pytest.raises(SetupError, match="samepage-fix"):
        wire_rooms("http://x", "agent-42", "k", env, only_ask)


def test_helpers() -> None:
    assert parse_env('export A="1"\n# c\nB=two\nbad line\n') == {"A": "1", "B": "two"}
    assert room_ids([{"id": "1", "name": "a"}, "junk", {"name": "b"}]) == {"a": "1"}
    assert room_ids({"not": "a list"}) == {}


def test_set_env_values_appends_new_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    set_env_values(env, {"A": "1"})
    set_env_values(env, {"A": "2", "B": "3"})
    assert env.read_text() == "A=2\nB=3\n"

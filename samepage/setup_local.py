"""One-command setup against a Switch server that Switch Console runs on this computer.

`samepage connect` finds the local server Console started, signs in as its admin
with the credentials Console generated, mints a *personal* registration key (so the
arbiter has the same owner as the worker agents, ADR 0001 V5/V6), registers the
arbiter, and writes the address, agent id and agent key into `.env`. Nothing secret
is printed.

`samepage wire-rooms` (after the template has created the rooms) looks up the room
ids by name and writes them into `.env`.

Verified against sandbox-quantum/switch @ 7e1316f:
- Console's native server writes its settings to `<userData>/…/run/switch-core.env`
  (console/.../managed-switch-server/native/core-process.ts, CORE_ENV_FILE) with
  SERVER_PORT and GATEWAY_ADMIN_PASSWORD (native/core-settings.ts); userData is
  `~/Library/Application Support/switchdash` on macOS (main/app/user-data-dir.ts).
- The admin account is `admin@switch.local` (constants.ts, LOCAL_SERVER_ADMIN_EMAIL).
- The Gateway API is mounted at `/gateway` on the server's one address (core main.py);
  `POST /gateway/auth/login` sets a session cookie; `POST /gateway/api-keys` returns
  `{id, label, key, created_at}` (gateway/api_keys.py, schemas.py).
- `list_rooms` returns `[{room_id, name, …}]` (bridges/agent/operations/definitions.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

DEFAULT_SWITCH_DIR = Path("~/Library/Application Support/switchdash")
ADMIN_EMAIL = "admin@switch.local"
ROOM_KEYS = {
    "samepage-ask": "SAMEPAGE_ASK_ROOM",
    "samepage-fix": "SAMEPAGE_FIX_ROOM",
}
DESK_ROOMS = {"samepage-desk-claude": "samepage-claude", "samepage-desk-codex": "samepage-codex"}


class SetupError(RuntimeError):
    """A step failed; the message says what to do."""


def find_core_env(base: Path) -> Path | None:
    """The most recently written switch-core.env under Console's data folder."""
    base = base.expanduser()
    if not base.exists():
        return None
    found = sorted(base.rglob("switch-core.env"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip('"').strip("'")
    return values


def set_env_values(path: Path, updates: dict[str, str]) -> None:
    """Replace `KEY=...` lines (commented-out ones too) or append them. Other lines are kept."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done: set[str] = set()
    out = []
    for line in lines:
        bare = line.lstrip("# ").split("=", 1)[0].strip()
        if bare in updates and "=" in line:
            if bare not in done:
                out.append(f"{bare}={updates[bare]}")
                done.add(bare)
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    path.chmod(0o600)


def registration_body(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": "SamePage",
        "description": "SamePage Arbiter: collects sealed answers, checks evidence, records human rulings",
        "connector_type": "SamePage Arbiter",
        "integration_profile": {
            "connection_model": "always_on",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }


def connect(switch_dir: Path, env_file: Path, agent_name: str, http: httpx.Client | None = None) -> dict[str, str]:
    """Register the arbiter on the local server and write its settings to `env_file`.

    Returns the non-secret values written (url and agent id) for display.
    """
    core_env = find_core_env(switch_dir)
    if core_env is None:
        raise SetupError(f"No local Switch server found under {switch_dir}. Start it in Switch Console first.")
    values = parse_env(core_env.read_text(encoding="utf-8"))
    port, password = values.get("SERVER_PORT"), values.get("GATEWAY_ADMIN_PASSWORD")
    if not port or not password:
        raise SetupError(f"{core_env} has no SERVER_PORT or GATEWAY_ADMIN_PASSWORD; is this a Console-run server?")
    url = f"http://localhost:{port}"
    client = http or httpx.Client(timeout=20)

    try:
        health = client.get(f"{url}/health")
    except httpx.HTTPError as exc:
        raise SetupError(f"The server at {url} isn't answering ({exc}). Click Start in Switch Console.") from exc
    if health.status_code != 200:
        raise SetupError(f"{url}/health answered {health.status_code}. Click Start in Switch Console.")

    email = values.get("GATEWAY_ADMIN_EMAIL", ADMIN_EMAIL)
    login = client.post(f"{url}/gateway/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        raise SetupError(f"Signing in to the local server failed ({login.status_code}): {login.text[:200]}")
    # Send the session cookie explicitly: a cookie marked Secure would not be sent over http by a jar.
    cookie = "; ".join(f"{k}={v}" for k, v in login.cookies.items())
    key_resp = client.post(f"{url}/gateway/api-keys", json={"label": agent_name}, headers={"Cookie": cookie})
    if key_resp.status_code != 200:
        raise SetupError(f"Creating a registration key failed ({key_resp.status_code}): {key_resp.text[:200]}")
    registration_key = str(key_resp.json()["key"])

    reg = client.post(
        f"{url}/agents", json=registration_body(agent_name), headers={"Authorization": f"Bearer {registration_key}"}
    )
    if reg.status_code != 200:
        hint = (
            " An agent with this name may already exist: delete it in Switch Console (Your Agents) or set "
            "SWITCH_AGENT_NAME to a new name."
            if reg.status_code in (400, 409)
            else ""
        )
        raise SetupError(f"Registering {agent_name} failed ({reg.status_code}): {reg.text[:200]}.{hint}")
    data = reg.json()
    set_env_values(
        env_file,
        {
            "SWITCH_API_URL": url,
            "SWITCH_AGENT_NAME": agent_name,
            "SWITCH_AGENT_ID": str(data["id"]),
            "SWITCH_AGENT_API_KEY": str(data["api_key"]),
        },
    )
    return {"url": url, "agent_id": str(data["id"])}


def room_ids(rooms: Any) -> dict[str, str]:
    """Map room name -> room id from a list_rooms result."""
    out: dict[str, str] = {}
    for room in rooms if isinstance(rooms, list) else []:
        if isinstance(room, dict) and room.get("name") and (room.get("room_id") or room.get("id")):
            out[str(room["name"])] = str(room.get("room_id") or room.get("id"))
    return out


def wire_rooms(
    url: str, agent_id: str, agent_key: str, env_file: Path, http: httpx.Client | None = None
) -> dict[str, str]:
    client = http or httpx.Client(timeout=20)
    resp = client.post(
        f"{url.rstrip('/')}/agents/{agent_id}/ops/list_rooms", json={}, headers={"Authorization": f"Bearer {agent_key}"}
    )
    if resp.status_code != 200:
        raise SetupError(f"Listing the arbiter's rooms failed ({resp.status_code}): {resp.text[:200]}")
    found = room_ids(resp.json().get("result"))
    missing = [name for name in [*ROOM_KEYS, *DESK_ROOMS] if name not in found]
    if missing:
        raise SetupError(
            "The arbiter isn't in these rooms yet: "
            + ", ".join(missing)
            + ". Create them from switch/samepage.template.yaml in Switch Console first. "
            + f"Rooms it can see: {', '.join(sorted(found)) or 'none'}."
        )
    updates = {key: found[name] for name, key in ROOM_KEYS.items()}
    updates["SAMEPAGE_DESKS"] = ",".join(f"{worker}={found[room]}" for room, worker in DESK_ROOMS.items())
    set_env_values(env_file, updates)
    return updates

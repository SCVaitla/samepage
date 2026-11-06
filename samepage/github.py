"""Read-only GitHub checks on the fix PR. SamePage never merges; there is no merge call here.

Uses a fine-grained token scoped to the one demo docs repo.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx

PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")


@dataclass(frozen=True)
class PullRequest:
    url: str
    number: int
    head_ref: str
    base_ref: str
    state: str
    merged: bool
    diff: str


class GitHub:
    def __init__(self, token: str, repo: str, http: httpx.AsyncClient | None = None) -> None:
        self.repo = repo
        self.http = http or httpx.AsyncClient(base_url="https://api.github.com", timeout=20)
        self.headers = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}

    async def _get(self, path: str, accept: str) -> httpx.Response:
        for attempt in range(3):
            try:
                r = await self.http.get(path, headers={**self.headers, "Accept": accept})
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    return r
            except httpx.TransportError:
                pass
            await asyncio.sleep(2**attempt)
        raise RuntimeError(f"GitHub did not answer for {path}")

    async def pull_request(self, url: str) -> PullRequest:
        m = PR_URL.search(url)
        if m is None:
            raise ValueError("not a GitHub pull request URL")
        if m.group(1).lower() != self.repo.lower():
            raise ValueError(f"PR is in {m.group(1)}, but SamePage only works on {self.repo}")
        number = int(m.group(2))
        meta = (await self._get(f"/repos/{self.repo}/pulls/{number}", "application/vnd.github+json")).json()
        diff = (await self._get(f"/repos/{self.repo}/pulls/{number}", "application/vnd.github.diff")).text
        return PullRequest(
            url=m.group(0),
            number=number,
            head_ref=meta["head"]["ref"],
            base_ref=meta["base"]["ref"],
            state=meta["state"],
            merged=bool(meta.get("merged")),
            diff=diff,
        )

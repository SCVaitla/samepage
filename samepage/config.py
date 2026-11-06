"""All settings come from the environment (or .env). Nothing secret has a default."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # Where the docs live. In the demo this is a git checkout of the demo docs repo.
    corpus_dir: Path = Field(default=Path("corpus"), alias="SAMEPAGE_CORPUS_DIR")
    db_path: Path = Field(default=Path("samepage.sqlite"), alias="SAMEPAGE_DB_PATH")

    # Corpus scan: a passage must contain at least this many of the claim's anchor words
    # (from its entity) to count as "about the same fact".
    min_anchor_terms: int = Field(default=1, alias="SAMEPAGE_MIN_ANCHOR_TERMS")
    # How many lines an agent's cited span may be off by and still verify.
    quote_slack_lines: int = Field(default=2, alias="SAMEPAGE_QUOTE_SLACK_LINES")
    # Question equivalence: cosine similarity needed to map a question onto a known one.
    equivalence_threshold: float = Field(default=0.35, alias="SAMEPAGE_EQUIVALENCE_THRESHOLD")

    # Who may rule on any case, besides the owners of the losing sources. Comma-separated usernames.
    approvers: str = Field(default="", alias="SAMEPAGE_APPROVERS")

    max_answer_bytes: int = Field(default=64_000, alias="SAMEPAGE_MAX_ANSWER_BYTES")

    # The demo docs repo, cloned locally for the engine. When set, the engine reads the
    # docs at `origin/<ref>` (main, or a fix branch for retests). When empty, corpus_dir.
    docs_repo_dir: Path | None = Field(default=None, alias="SAMEPAGE_DOCS_REPO_DIR")
    docs_subdir: str = Field(default="", alias="SAMEPAGE_DOCS_SUBDIR")

    # Rooms (Switch room ids) and agent names. Desks: "worker=room_id,worker=room_id".
    ask_room: str = Field(default="", alias="SAMEPAGE_ASK_ROOM")
    desks: str = Field(default="", alias="SAMEPAGE_DESKS")
    fix_room: str = Field(default="", alias="SAMEPAGE_FIX_ROOM")
    fixer_name: str = Field(default="samepage-fixer", alias="SAMEPAGE_FIXER")

    agent_timeout_s: float = Field(default=240.0, alias="SAMEPAGE_AGENT_TIMEOUT")
    batch_size: int = Field(default=6, alias="SAMEPAGE_BATCH_SIZE")
    retest_questions: int = Field(default=4, alias="SAMEPAGE_RETEST_QUESTIONS")
    golden_path: Path = Field(default=Path("eval/golden.yaml"), alias="SAMEPAGE_GOLDEN")
    reports_dir: Path = Field(default=Path("reports"), alias="SAMEPAGE_REPORTS_DIR")

    def desk_map(self) -> dict[str, str]:
        pairs = [p.split("=", 1) for p in self.desks.split(",") if "=" in p]
        return {w.strip(): r.strip() for w, r in pairs}

    # Switch agent protocol (the arbiter). Secrets have no defaults.
    switch_api_url: str = Field(default="http://127.0.0.1:8000", alias="SWITCH_API_URL")
    switch_agent_id: str = Field(default="", alias="SWITCH_AGENT_ID")
    switch_agent_api_key: str = Field(default="", alias="SWITCH_AGENT_API_KEY")
    switch_agent_name: str = Field(default="samepage-arbiter", alias="SWITCH_AGENT_NAME")

    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_demo_repo: str = Field(default="", alias="GITHUB_DEMO_REPO")

    def approver_set(self) -> set[str]:
        return {a.strip().lstrip("@").lower() for a in self.approvers.split(",") if a.strip()}

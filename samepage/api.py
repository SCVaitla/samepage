"""HTTP API of the SamePage Engine. The room (via the arbiter) is the main interface;
this API serves health checks, integration tests and debugging."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from samepage import __version__
from samepage.cards import investigation_card
from samepage.classify import Engine
from samepage.config import Settings
from samepage.corpus import Corpus
from samepage.parse import parse_answer
from samepage.store import Store
from samepage.trust import ledger


class RawAnswer(BaseModel):
    agent: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    raw: str = Field(max_length=64_000)


class EvaluateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    answers: list[RawAnswer] = Field(min_length=1, max_length=4)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    app = FastAPI(title="SamePage Engine", version=__version__)

    @lru_cache(maxsize=1)
    def engine() -> Engine:
        return Engine(Corpus.from_dir(s.corpus_dir), s.quote_slack_lines, s.min_anchor_terms)

    @lru_cache(maxsize=1)
    def store() -> Store:
        return Store(s.db_path)

    @app.middleware("http")
    async def limit_body(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        size = request.headers.get("content-length")
        if size is not None and size.isdigit() and int(size) > 2 * s.max_answer_bytes:
            return JSONResponse({"detail": "payload too large"}, status_code=413)
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"ok": True, "version": __version__}

    @app.post("/v1/evaluate")
    def evaluate(req: EvaluateRequest) -> dict[str, object]:
        answers = [parse_answer(a.agent, a.raw, max_bytes=s.max_answer_bytes) for a in req.answers]
        result = engine().evaluate(req.question, answers)
        return {
            "outcome": result.outcome.value,
            "reasons": result.reasons,
            "card": investigation_card("preview", result, s.switch_agent_name),
            "result": result.model_dump(),
        }

    @app.get("/v1/trust")
    def trust() -> list[dict[str, object]]:
        return [
            {"source": r.source_id, "wins": r.wins, "losses": r.losses, "loss_rate": r.loss_rate}
            for r in ledger(store())
        ]

    @app.get("/v1/cases/{case_id}/history")
    def history(case_id: str) -> list[dict[str, object]]:
        if not (len(case_id) == 8 and all(c in "0123456789abcdef" for c in case_id)):
            raise HTTPException(422, "case ids are 8 hex characters")
        return store().history(case_id)

    return app

"""Turn an agent's raw room message into an AgentAnswer.

Agents are asked to reply with only a fenced ```json block in the Answer Contract
shape. Anything else becomes an AgentAnswer with an error, which the classifier turns
into UNSUPPORTED (never VERIFIED).
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import ValidationError

from samepage.models import AgentAnswer, AnswerContract

FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_answer(agent: str, raw: str, sealed_at: str = "", max_bytes: int = 64_000) -> AgentAnswer:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def fail(error: str) -> AgentAnswer:
        return AgentAnswer(agent=agent, raw=raw[:max_bytes], sealed_at=sealed_at, sha256=digest, error=error)

    if len(raw.encode("utf-8")) > max_bytes:
        return fail(f"answer larger than {max_bytes} bytes")
    match = FENCE.search(raw)
    body = match.group(1) if match else raw.strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return fail(f"invalid_json: {exc.msg}")
    if not isinstance(data, dict):
        return fail("invalid_json: expected an object")
    try:
        contract = AnswerContract.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        return fail(f"contract_violation: {where}: {first['msg']}")
    return AgentAnswer(agent=agent, raw=raw, sealed_at=sealed_at, sha256=digest, contract=contract)


def parse_batch(
    agent: str, raw: str, question_ids: list[str], sealed_at: str = "", max_bytes: int = 64_000
) -> dict[str, AgentAnswer]:
    """Split one reply holding several fenced JSON blocks into one answer per question id.

    A question with no block (or a block that does not parse) gets an answer with an error,
    so it ends UNSUPPORTED rather than silently missing.
    """
    if len(raw.encode("utf-8")) > max_bytes:
        return {q: parse_answer(agent, raw, sealed_at, max_bytes) for q in question_ids}
    by_id: dict[str, AgentAnswer] = {}
    blocks = FENCE.findall(raw)
    for i, body in enumerate(blocks):
        parsed = parse_answer(agent, f"```json\n{body}\n```", sealed_at, max_bytes)
        qid = parsed.contract.question_id if parsed.contract else ""
        if not qid and len(question_ids) == len(blocks):
            qid = question_ids[i]  # unlabeled blocks in the asked order
        if qid in question_ids and qid not in by_id:
            by_id[qid] = parsed
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    for q in question_ids:
        if q not in by_id:
            by_id[q] = AgentAnswer(
                agent=agent,
                raw=raw[:2000],
                sealed_at=sealed_at,
                sha256=digest,
                error=f"no valid answer block for {q}",
            )
    return by_id


def timed_out(agent: str, seconds: float) -> AgentAnswer:
    return AgentAnswer(agent=agent, raw="", error=f"timeout after {seconds:.0f}s")

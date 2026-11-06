# ADR 0002: The engine is deterministic; the agents do the reading

- **Status:** Accepted
- **Date:** 2026-11-05
- **Roles:** Architect (author), Backend Engineer, QA Engineer

## Context

The brief allows LLM calls in the engine for claim extraction and normalization, at temperature 0 and cached. It does not require them. In the build environment there is no LLM API key and no access to Hugging Face for a local embedding model. More importantly, the judges must be able to watch the same input give the same verdict, and the human must be able to explain every rule.

## Decision

The engine makes **no model calls**. The worker agents (Claude Code and Codex) are the language models. They read the docs and return structured claims with verbatim quotes, as the Answer Contract requires. The engine:

1. **Verifies** each quote character for character at the cited lines (`samepage/evidence.py`). Whitespace runs count as one space, and a citation may be off by up to 2 lines (`SAMEPAGE_QUOTE_SLACK_LINES`).
2. **Normalizes** values with generic rules (`samepage/values.py`): units (days, weeks, months, years), seats/members/users, requests per minute/hour/second including the "1k" shorthand, 24/7 wordings, yes/no words, and plan availability ("all plans", "Enterprise only", "not available on Starter", with question sentences ignored). None of the rules names a planted fact.
3. **Scans** the corpus for every passage stating a value of the same kind for the same fact (`samepage/classify.py`, `Engine.scan`). A passage counts when it contains an anchor word from the claim's entity (via the company glossary), names the plan in question (or says "all plans"), and yields a value of the same kind.
4. **Classifies** with an ordered rule list (`Engine.evaluate`). The first match wins, and the order is written at the top of the file.

**Question equivalence** uses TF-IDF over glossary-aware word tokens and character 3-grams, with cosine similarity (`samepage/equivalence.py`). It sits behind an `Embedder` protocol, so a sentence-transformers model can replace it. The threshold is config (`SAMEPAGE_EQUIVALENCE_THRESHOLD`, default 0.35, chosen on the golden paraphrases, never on H1).

**Company glossary** (`corpus/glossary.yaml`) maps phrases that mean the same thing ("SSO", "single sign-on", "SAML") to one token. It is data the docs owners maintain, not code.

## Definitions this forces

- **VERIFIED vs COMPATIBLE.** Both are agreement with no contradicting passage. COMPATIBLE means the evidence words the value differently ("24/7" vs "round-the-clock", "1k rpm" vs "1,000 requests per minute"). VERIFIED means every piece of evidence uses the same words. For yes/no facts there is no wording to compare, so agreement is VERIFIED.
- **One agent unknown, the other answered with a verified quote** → CONFLICT. Disagreement is the alarm, even when one side is silence.
- **An agent's headline quote fails verification** → UNSUPPORTED. This holds even when the other agent is fine; the card says which claim failed.

## Consequences

- Same input, same output, with no cache needed. Tests run in under 10 seconds with no network.
- Recall is limited by the normalizer and the scan. Facts whose values are free text ("blue", "Okta and Entra") are compared as normalized text and are not cross-checked against the corpus. The card says so ("the engine cannot scan the docs for this kind of value").
- Lexical question matching can't tell some near topics apart. "Is there phone support?" scores 0.72 against "What are the support hours?". This is listed under Known Limitations.

"""Evidence verification: quotes must exist verbatim (whitespace-insensitive) at the cited lines."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from samepage.evidence import find_span, verify_quote
from samepage.models import ContractClaim
from tests.helpers import claim, corpus


def test_real_quote_verifies_and_reports_tight_span() -> None:
    c = claim("product_spec.md", "Starter workspaces are limited to 5 seats", "5")
    result = verify_quote(corpus(), c)
    assert result.ok
    assert result.line_start == result.line_end == c.line_start


def test_quote_across_a_line_wrap_verifies() -> None:
    quote = "Single sign-on (SSO) through SAML 2.0 is an Enterprise plan feature. It is not available on the Starter"
    c = claim("product_spec.md", quote, "false")
    assert c.line_end == c.line_start + 1
    assert verify_quote(corpus(), c).ok


def test_off_by_two_lines_still_verifies_but_three_does_not() -> None:
    c = claim("product_spec.md", "Starter workspaces are limited to 5 seats", "5")
    near = c.model_copy(update={"line_start": c.line_start - 2, "line_end": c.line_end - 2})
    far = c.model_copy(update={"line_start": c.line_start - 3, "line_end": c.line_end - 3})
    assert verify_quote(corpus(), near).ok
    assert not verify_quote(corpus(), far).ok


def test_paraphrased_quote_fails() -> None:
    c = claim("product_spec.md", "Starter workspaces are limited to 5 seats", "5")
    bad = c.model_copy(update={"quote": "Starter workspaces are capped at 5 seats"})
    assert "not found" in verify_quote(corpus(), bad).reason


def test_unknown_file_short_quote_and_reversed_span_fail() -> None:
    base = claim("product_spec.md", "Starter workspaces are limited to 5 seats", "5")
    assert "not in the corpus" in verify_quote(corpus(), base.model_copy(update={"source_path": "x/y.md"})).reason
    assert "too short" in verify_quote(corpus(), base.model_copy(update={"quote": "5 seats"})).reason
    reversed_span = base.model_copy(update={"line_start": base.line_start + 1, "line_end": base.line_start})
    assert "before" in verify_quote(corpus(), reversed_span).reason


def test_path_forms_are_accepted() -> None:
    c = corpus()
    assert c.normalize_path("corpus/website/faq.md") == "website/faq.md"
    assert c.normalize_path("./website/faq.md") == "website/faq.md"
    assert c.normalize_path("website/faq.md") == "website/faq.md"
    assert c.normalize_path("../secrets.md") is None


# ---- property tests ------------------------------------------------------------------

lines_strategy = st.lists(
    st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40), min_size=1, max_size=8
)


@given(lines=lines_strategy, data=st.data())
def test_any_substring_of_the_file_is_found(lines: list[str], data: st.DataObject) -> None:
    joined = " ".join(" ".join(ln.split()) for ln in lines)
    joined = " ".join(joined.split())
    if not joined:
        return
    i = data.draw(st.integers(0, len(joined) - 1))
    j = data.draw(st.integers(i + 1, len(joined)))
    quote = joined[i:j]
    if not quote.strip():
        return
    assert find_span(lines, quote, 1, len(lines)) is not None


@given(lines=lines_strategy, extra=st.text(min_size=1, max_size=10))
def test_text_not_in_file_is_never_found(lines: list[str], extra: str) -> None:
    haystack = " ".join(" ".join(" ".join(lines).split()).split())
    needle = "\x00" + extra  # NUL never appears in the generated lines' collapsed text
    if needle in haystack:
        return
    assert find_span(lines, needle, 1, len(lines)) is None


@given(spaces=st.text(alphabet=" \t\n", min_size=1, max_size=5))
def test_whitespace_runs_do_not_matter(spaces: str) -> None:
    lines = ["Refunds are", "available within 14 days."]
    assert find_span(lines, f"Refunds{spaces}are{spaces}available", 1, 2) == (1, 2)


def test_unicode_quotes_are_matched_exactly() -> None:
    lines = ["Café plan — “Starter” includes 5 seats."]
    assert find_span(lines, "“Starter” includes 5 seats", 1, 1) == (1, 1)
    assert find_span(lines, '"Starter" includes 5 seats', 1, 1) is None  # straight quotes are different text


def test_claim_model_rejects_bad_lines() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ContractClaim(entity="a", attribute="b", value="c", source_path="p", line_start=0, line_end=1, quote="q")

"""Value normalization and plan availability."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from samepage.values import (
    extract_for,
    find_days,
    find_rates,
    find_schedules,
    find_seats,
    normalize_claim_value,
    plan_availability,
)

PLANS = ["starter", "pro", "enterprise"]


def keys(values: list) -> list[str]:  # type: ignore[type-arg]
    return [v.key for v in values]


def test_durations() -> None:
    assert keys(find_days("within 14 days")) == ["days:14"]
    assert keys(find_days("a 30-day guarantee")) == ["days:30"]
    assert keys(find_days("two weeks")) == ["days:14"]
    assert keys(find_days("kept for 1 year")) == ["days:365"]
    assert find_days("five to ten business days") == []  # a word between the number and the unit


def test_seats_and_rates() -> None:
    assert keys(find_seats("up to 10 members")) == ["seats:10"]
    assert find_seats("$8 per seat per month") == []
    assert keys(find_rates("1k rpm")) == ["per_min:1000"]
    assert keys(find_rates("1,000 requests per minute")) == ["per_min:1000"]
    assert keys(find_rates("60,000 requests per hour")) == ["per_min:1000"]


def test_schedules() -> None:
    for text in ("24/7", "round-the-clock", "around the clock", "24x7"):
        assert keys(find_schedules(text)) == ["schedule:24x7"], text


def test_plan_availability() -> None:
    assert plan_availability("SSO is included on all plans.", PLANS) == set(PLANS)
    spec = "SSO is an Enterprise plan feature. It is not available on the Starter or Pro plans."
    assert plan_availability(spec, PLANS) == {"enterprise"}
    assert plan_availability("Starter can enable SSO from admin settings.", PLANS) == {"starter"}
    assert plan_availability("SCIM is Enterprise only.", PLANS) == {"enterprise"}
    assert plan_availability("Not available on Starter.", PLANS) == {"pro", "enterprise"}
    assert plan_availability("Sign in with Google.", PLANS) is None
    assert plan_availability("anything", []) is None


def test_claim_values() -> None:
    assert normalize_claim_value("Enterprise only", "", "available", "starter", PLANS).key == "bool:false"
    assert normalize_claim_value("no", "", "available", None, PLANS).key == "bool:false"
    assert normalize_claim_value("10", "Up to 10 seats per workspace", "limit", None, PLANS).key == "seats:10"
    assert normalize_claim_value("5", "no unit here", "seat_limit", None, PLANS).key == "seats:5"
    assert normalize_claim_value("14", "", "refund_window", None, PLANS).key == "days:14"
    assert normalize_claim_value("7", "", "colour", None, PLANS).key == "number:7"
    assert normalize_claim_value("Blue and green", "", "colour", None, PLANS).key == "text:blue_and_green"


def test_extract_nearest_to_the_plan() -> None:
    text = "Pro workspaces can make 1,000 requests per minute, and Enterprise workspaces 5,000 requests per minute."
    assert extract_for("per_min", text, "pro", PLANS).key == "per_min:1000"  # type: ignore[union-attr]
    assert extract_for("per_min", text, "enterprise", PLANS).key == "per_min:5000"  # type: ignore[union-attr]
    assert extract_for("per_min", "1k rpm for everyone", "pro", PLANS).key == "per_min:1000"  # type: ignore[union-attr]
    assert extract_for("bool", "No plans named", None, PLANS) is None
    assert extract_for("days", "no numbers", None, PLANS) is None


@given(n=st.integers(1, 9999))
def test_number_formats_agree(n: int) -> None:
    a = find_rates(f"{n} requests per minute")[0].key
    b = find_rates(f"{n:,} requests/min")[0].key
    assert a == b == f"per_min:{n}"

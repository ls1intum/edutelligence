"""Request-level SLO resolution (``logos.request_slo``)."""

from logos.request_slo import SLO_PRIORITY, parse_slo_header, resolve_request_slo, slo_of_priority


def test_slo_priority_matches_key_slo_tiers():
    assert SLO_PRIORITY == {
        "ux-critical": 10,
        "ux-high-prio": 5,
        "ux-background": 1,
    }


def test_slo_of_priority_maps_exact_tiers():
    assert slo_of_priority(10) == "ux-critical"
    assert slo_of_priority(1) == "ux-background"
    assert slo_of_priority(5) == "ux-high-prio"
    assert slo_of_priority(7) == "ux-high-prio"


def test_parse_slo_header_accepts_both_names_case_insensitively():
    assert parse_slo_header({"X-Logos-SLO": "ux-critical"}) == "ux-critical"
    assert parse_slo_header({"logos-slo": "UX-BACKGROUND"}) == "ux-background"
    assert parse_slo_header({"x-logos-slo": "ux-high-prio"}) == "ux-high-prio"


def test_parse_slo_header_ignores_unknown_values():
    assert parse_slo_header({"X-Logos-SLO": "not-a-tier"}) is None
    assert parse_slo_header({"X-Logos-SLO": ""}) is None
    assert parse_slo_header({}) is None


def test_resolve_uses_base_priority_without_headers():
    slo = resolve_request_slo({}, base_priority=5)
    assert slo.tier == "ux-high-prio"
    assert slo.priority == 5
    assert slo.fast_lane is False


def test_resolve_header_overrides_base_priority():
    slo = resolve_request_slo({"X-Logos-SLO": "ux-critical"}, base_priority=1)
    assert slo.tier == "ux-critical"
    assert slo.priority == 10
    assert slo.fast_lane is False


def test_cli_bg_sets_fast_lane_without_changing_priority():
    """cli-bg must not jump SLO tiers — that would starve same-bucket traffic
    differently from the bounded interleave. It only joins the fast lane."""
    slo = resolve_request_slo({"x-app": "cli-bg"}, base_priority=5)
    assert slo.priority == 5
    assert slo.tier == "ux-high-prio"
    assert slo.fast_lane is True


def test_cli_bg_with_explicit_slo_header_keeps_header_priority():
    slo = resolve_request_slo(
        {"x-app": "cli-bg", "logos-slo": "ux-background"},
        base_priority=10,
    )
    assert slo.priority == 1
    assert slo.tier == "ux-background"
    assert slo.fast_lane is True

"""Request-level SLO resolution (``logos.request_slo``).

The request SLO builds on the SLO that already exists on the API key
(``ux-critical`` / ``ux-high-prio`` / ``ux-background`` → ``default_priority``
10 / 5 / 1): the resolved key/team/policy priority is the request's queue
priority, and ``x-app: cli-bg`` only adds the same-bucket fast lane on top.
"""

from logos.request_slo import SLO_PRIORITY, is_cli_bg, resolve_request_slo, slo_of_priority


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
    # Inherited or admin-set values that are not exact tier values read as
    # the default tier, matching sloOfPriority in logos-ui key-slo.ts.
    assert slo_of_priority(7) == "ux-high-prio"
    assert slo_of_priority(0) == "ux-high-prio"


def test_is_cli_bg_only_flags_the_cli_bg_header():
    assert is_cli_bg({"x-app": "cli-bg"}) is True
    # HTTP headers are case-insensitive in name; compare the value the same
    # way.
    assert is_cli_bg({"X-App": "CLI-BG"}) is True
    assert is_cli_bg({"x-app": " cli-bg "}) is True
    # Interactive Claude Code sessions and anything unrecognised stay plain.
    assert is_cli_bg({"x-app": "cli"}) is False
    assert is_cli_bg({"x-app": "other-app"}) is False
    assert is_cli_bg({"user-agent": "claude-cli/1.0"}) is False
    assert is_cli_bg({}) is False


def test_resolve_keeps_the_base_priority():
    """The resolved key/team/policy SLO is the request's queue priority;
    nothing in request_slo may move it between buckets."""
    slo = resolve_request_slo({}, base_priority=5)
    assert slo.tier == "ux-high-prio"
    assert slo.priority == 5
    assert slo.fast_lane is False

    slo = resolve_request_slo({}, base_priority=10)
    assert slo.tier == "ux-critical"
    assert slo.priority == 10
    assert slo.fast_lane is False

    slo = resolve_request_slo({}, base_priority=1)
    assert slo.tier == "ux-background"
    assert slo.priority == 1
    assert slo.fast_lane is False


def test_resolve_tier_of_a_non_exact_priority_reads_as_default():
    slo = resolve_request_slo({}, base_priority=7)
    assert slo.tier == "ux-high-prio"
    assert slo.priority == 7
    assert slo.fast_lane is False


def test_cli_bg_sets_fast_lane_without_changing_priority():
    """cli-bg must not jump SLO tiers — that would starve same-bucket traffic
    differently from the bounded interleave. It only joins the fast lane."""
    slo = resolve_request_slo({"x-app": "cli-bg"}, base_priority=5)
    assert slo.priority == 5
    assert slo.tier == "ux-high-prio"
    assert slo.fast_lane is True


def test_cli_bg_with_a_low_slo_stays_in_its_bucket():
    """The fast lane applies within the key's SLO bucket: a ux-background
    key's cli-bg traffic stays LOW and gets the lane there, not a jump to
    NORMAL or HIGH."""
    slo = resolve_request_slo({"x-app": "cli-bg"}, base_priority=1)
    assert slo.priority == 1
    assert slo.tier == "ux-background"
    assert slo.fast_lane is True


def test_no_header_can_change_the_priority():
    """There is deliberately no per-request SLO override header: the SLO that
    exists is the key's, and a caller-controlled override would be an
    unbounded jump into another bucket (e.g. claiming ux-critical)."""
    slo = resolve_request_slo({"X-Logos-SLO": "ux-critical", "logos-slo": "ux-background"}, base_priority=5)
    assert slo.priority == 5
    assert slo.tier == "ux-high-prio"
    assert slo.fast_lane is False

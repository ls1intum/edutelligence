"""Unit tests for per-request SLO headers and admin queue-rank folding."""

from logos.pipeline.pipeline import effective_queue_role_rank, queue_role_rank
from logos.pipeline.request_slo import (
    VALID_SLOS,
    parse_request_slo_header,
    parse_workflow_tag_header,
    resolve_request_priority,
    slo_to_priority,
)
from logos.queue import Priority


def test_valid_slos_are_the_three_ux_tiers():
    assert VALID_SLOS == frozenset({"ux-critical", "ux-high-prio", "ux-background"})


def test_slo_to_priority_maps_tiers():
    assert slo_to_priority("ux-critical") == 10
    assert slo_to_priority("ux-high-prio") == 5
    assert slo_to_priority("ux-background") == 1


def test_parse_request_slo_header_accepts_known_values():
    assert parse_request_slo_header({"X-Logos-SLO": "ux-critical"}) == "ux-critical"
    assert parse_request_slo_header({"x-logos-slo": "UX-HIGH-PRIO"}) == "ux-high-prio"
    assert parse_request_slo_header({"logos-slo": "ux-background"}) == "ux-background"


def test_parse_request_slo_header_rejects_unknown_or_missing():
    assert parse_request_slo_header({}) is None
    assert parse_request_slo_header({"X-Logos-SLO": "urgent"}) is None
    assert parse_request_slo_header({"X-Logos-SLO": "  "}) is None
    assert parse_request_slo_header(None) is None


def test_parse_workflow_tag_header_accepts_aliases():
    assert parse_workflow_tag_header({"X-Logos-Workflow-Tag": "checkout.pay"}) == "checkout.pay"
    assert parse_workflow_tag_header({"x-logos-workflow-tag": " step "}) == "step"
    assert parse_workflow_tag_header({"logos-workflow-tag": "batch.nightly"}) == "batch.nightly"
    assert parse_workflow_tag_header({}) is None
    assert parse_workflow_tag_header({"X-Logos-Workflow-Tag": ""}) is None


def test_resolve_request_priority_header_slo_wins():
    # Header beats tag, key, team, and policy.
    assert resolve_request_priority("ux-background", "ux-critical", 10, 10, 10) == 1
    assert resolve_request_priority("ux-critical", "ux-background", 1, 1, 1) == 10


def test_resolve_request_priority_tag_slo_beats_key_team_policy():
    assert resolve_request_priority(None, "ux-critical", 1, 5, 10) == 10
    assert resolve_request_priority(None, "ux-background", 10, 10, 10) == 1


def test_resolve_request_priority_falls_back_to_key_team_policy_chain():
    assert resolve_request_priority(None, None, 10, 5, 1) == 10
    assert resolve_request_priority(None, None, 0, 5, 1) == 5
    assert resolve_request_priority(None, None, 0, 0, 1) == 1
    assert resolve_request_priority(None, None, 0, 0, 0) == int(Priority.NORMAL)


def test_effective_queue_role_rank_unranked_matches_base():
    assert effective_queue_role_rank("application", None) == queue_role_rank("application", None)
    assert effective_queue_role_rank("developer", "app_admin") == 1
    assert effective_queue_role_rank("developer", "app_developer", None) == 0


def test_effective_queue_role_rank_folds_admin_rank():
    # Lower admin rank number → higher effective role_rank.
    # (100000 - rank) * 10 + base_role_rank
    assert effective_queue_role_rank("application", None, 1) == (100000 - 1) * 10 + 2
    assert effective_queue_role_rank("application", None, 2) == (100000 - 2) * 10 + 2
    assert effective_queue_role_rank("developer", "app_admin", 3) == (100000 - 3) * 10 + 1
    assert effective_queue_role_rank("developer", None, 10) == (100000 - 10) * 10 + 0
    # Rank 1 beats rank 2 within the same base role.
    assert effective_queue_role_rank("application", None, 1) > effective_queue_role_rank("application", None, 2)

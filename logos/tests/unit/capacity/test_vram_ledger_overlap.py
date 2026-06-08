"""Tests for vram_ledger.has_overlapping_reservation (Phase 3.4)."""

from logos.capacity.vram_ledger import VRAMLedger


def test_no_reservations_returns_false():
    ledger = VRAMLedger()
    assert ledger.has_overlapping_reservation(1, frozenset({0, 1})) is False


def test_disjoint_gpus_no_overlap():
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="laneA",
        operation="load",
        vram_mb=4096.0,
        gpu_devices="0",
    )
    assert ledger.has_overlapping_reservation(1, frozenset({1})) is False
    assert ledger.has_overlapping_reservation(1, frozenset({2, 3})) is False


def test_overlapping_gpus_detects_overlap():
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="laneA",
        operation="load",
        vram_mb=4096.0,
        gpu_devices="0,1",
    )
    assert ledger.has_overlapping_reservation(1, frozenset({1})) is True
    assert ledger.has_overlapping_reservation(1, frozenset({0, 2})) is True


def test_different_provider_no_overlap():
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="laneA",
        operation="load",
        vram_mb=4096.0,
        gpu_devices="0",
    )
    # Different provider, same GPU index — no overlap (provider-scoped).
    assert ledger.has_overlapping_reservation(2, frozenset({0})) is False


def test_unspecified_target_gpus_treated_as_overlap():
    """If the reservation has unspecified gpu_devices (could land anywhere),
    we conservatively treat it as overlapping."""
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="laneA",
        operation="load",
        vram_mb=4096.0,
        gpu_devices=None,
    )
    assert ledger.has_overlapping_reservation(1, frozenset({0})) is True
    assert ledger.has_overlapping_reservation(1, frozenset({0, 1, 2})) is True


def test_unspecified_query_gpus_treated_as_overlap():
    """If the caller queries with no constraint, any reservation on this
    provider counts as overlap."""
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="laneA",
        operation="load",
        vram_mb=4096.0,
        gpu_devices="3",
    )
    assert ledger.has_overlapping_reservation(1, frozenset()) is True


def test_release_clears_overlap():
    ledger = VRAMLedger()
    rid = ledger.reserve(
        provider_id=1,
        lane_id="laneA",
        operation="load",
        vram_mb=4096.0,
        gpu_devices="0",
    )
    assert ledger.has_overlapping_reservation(1, frozenset({0})) is True
    ledger.release(rid)
    assert ledger.has_overlapping_reservation(1, frozenset({0})) is False

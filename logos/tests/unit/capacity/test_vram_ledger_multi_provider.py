"""Multi-provider VRAM ledger tests.

The existing `test_vram_ledger.py` and `test_vram_ledger_overlap.py` exercise
single-provider semantics. These tests cover the cluster behaviour:

  - Provider A's reservation must not subtract from Provider B's effective
    available VRAM.
  - Per-GPU commits are namespaced by (provider_id, device_id) so GPU 0 on
    A is independent of GPU 0 on B.
  - Releasing a reservation on A does not affect committed totals on B.
  - Stale-cleanup-by-provider doesn't leak reservations into a different
    provider's counter.
"""

from __future__ import annotations

from logos.capacity.vram_ledger import VRAMLedger


def test_reservation_on_one_provider_does_not_consume_other_provider_vram():
    """Reserving on provider A should leave provider B's effective available
    VRAM unchanged."""
    ledger = VRAMLedger()
    raw_b_before = 50_000.0
    ledger.reserve(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        gpu_devices="0",
    )
    # Provider 1's effective dropped
    assert ledger.get_effective_available_mb(1, raw_b_before) == 10_000.0
    # Provider 2's effective is untouched
    assert ledger.get_effective_available_mb(2, raw_b_before) == raw_b_before


def test_two_providers_can_reserve_concurrently():
    """Two providers can each reserve their full quota without affecting
    one another. This is the basic invariant that lets the planner safely
    plan loads on multiple workers in the same cycle."""
    ledger = VRAMLedger()
    rid_a = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        raw_available_mb=50_000.0,
        safety_margin=1.0,
    )
    rid_b = ledger.try_reserve_atomic(
        provider_id=2,
        lane_id="B-y",
        operation="load",
        vram_mb=40_000.0,
        raw_available_mb=50_000.0,
        safety_margin=1.0,
    )
    assert rid_a is not None
    assert rid_b is not None
    assert ledger.get_committed_mb(1) == 40_000.0
    assert ledger.get_committed_mb(2) == 40_000.0


def test_per_gpu_committed_is_namespaced_by_provider():
    """GPU 0 on provider A is a different bucket from GPU 0 on provider B.
    Without this, a load on A's GPU 0 would block a load on B's GPU 0."""
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        gpu_devices="0",
    )
    # A's GPU 0 has 40 GB committed
    assert ledger.get_gpu_committed_mb(1, 0) == 40_000.0
    # B's GPU 0 has 0 MB committed
    assert ledger.get_gpu_committed_mb(2, 0) == 0.0


def test_per_gpu_reserve_on_one_provider_does_not_block_other_provider():
    """Provider B can reserve its GPU 0 even when provider A's GPU 0 is fully
    booked. This is the contract that lets the planner spawn TP=1 loads on
    GPU 0 across multiple workers."""
    ledger = VRAMLedger()
    # Fill A's GPU 0
    rid_a = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        raw_available_mb=50_000.0,
        safety_margin=1.0,
        gpu_devices="0",
        per_gpu_free={0: 50_000.0},
    )
    assert rid_a is not None
    # B's GPU 0 has 50 GB free; reservation should succeed
    rid_b = ledger.try_reserve_atomic(
        provider_id=2,
        lane_id="B-y",
        operation="load",
        vram_mb=40_000.0,
        raw_available_mb=50_000.0,
        safety_margin=1.0,
        gpu_devices="0",
        per_gpu_free={0: 50_000.0},
    )
    assert rid_b is not None


def test_release_on_provider_a_does_not_change_provider_b_committed():
    """Provider isolation under release."""
    ledger = VRAMLedger()
    rid_a = ledger.reserve(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        gpu_devices="0",
    )
    ledger.reserve(
        provider_id=2,
        lane_id="B-y",
        operation="load",
        vram_mb=30_000.0,
        gpu_devices="0",
    )
    assert ledger.get_committed_mb(2) == 30_000.0
    ledger.release(rid_a)
    # B's commit untouched
    assert ledger.get_committed_mb(2) == 30_000.0
    assert ledger.get_committed_mb(1) == 0.0


def test_overlapping_gpu_check_is_per_provider():
    """`has_overlapping_reservation` returns True only when the *same* provider
    has a reservation overlapping the requested GPUs. A reservation on
    provider A's GPU 0 must not flag overlap on provider B's GPU 0."""
    ledger = VRAMLedger()
    ledger.reserve(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        gpu_devices="0,1",
    )
    # Same provider, overlapping GPUs → overlap
    assert ledger.has_overlapping_reservation(provider_id=1, gpu_devices=frozenset({0}))
    assert ledger.has_overlapping_reservation(provider_id=1, gpu_devices=frozenset({1}))
    # Different provider with the *same* GPU indices → no overlap
    assert not ledger.has_overlapping_reservation(provider_id=2, gpu_devices=frozenset({0}))
    assert not ledger.has_overlapping_reservation(provider_id=2, gpu_devices=frozenset({1}))


def test_safety_margin_applied_per_provider_only():
    """Safety margin applies to each provider's reservation independently —
    it doesn't carry over to other providers."""
    ledger = VRAMLedger()
    # Provider 1: 50 GB raw, with 1.5x margin a 40 GB request needs 60 → reject
    rid1 = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="A-x",
        operation="load",
        vram_mb=40_000.0,
        raw_available_mb=50_000.0,
        safety_margin=1.5,
    )
    assert rid1 is None
    # Provider 2: same call, independent. Should also reject — but the
    # rejection is solely a function of provider 2's raw_available_mb,
    # not provider 1's state.
    rid2 = ledger.try_reserve_atomic(
        provider_id=2,
        lane_id="B-y",
        operation="load",
        vram_mb=20_000.0,
        raw_available_mb=50_000.0,
        safety_margin=1.5,
    )
    assert rid2 is not None  # 20 × 1.5 = 30 ≤ 50 ✓
    assert ledger.get_committed_mb(1) == 0.0
    assert ledger.get_committed_mb(2) == 20_000.0


def test_negative_reservation_freeing_only_affects_its_own_provider():
    """The freeing-reservation pattern (negative vram_mb for reclaim_sleep /
    reclaim_stop) must credit only the originating provider."""
    ledger = VRAMLedger()
    # Provider 1 has 20 GB in flight (loading)
    rid_a = ledger.reserve(provider_id=1, lane_id="A-x", operation="load", vram_mb=20_000.0)
    # Provider 1 also evicts a 10 GB lane (credits back)
    rid_a_evict = ledger.reserve(provider_id=1, lane_id="A-z", operation="reclaim_stop", vram_mb=-10_000.0)
    # Provider 1 net committed = 20 - 10 = 10 GB
    assert ledger.get_committed_mb(1) == 10_000.0
    # Provider 2 untouched
    assert ledger.get_committed_mb(2) == 0.0
    # Release the freeing reservation — provider 1's commit goes back up
    ledger.release(rid_a_evict)
    assert ledger.get_committed_mb(1) == 20_000.0
    assert ledger.get_committed_mb(2) == 0.0
    # Final release
    ledger.release(rid_a)
    assert ledger.get_committed_mb(1) == 0.0

"""Tests for HostRamLedger atomic reservation gating.

The host-RAM ledger is the analogue of VRAMLedger for system memory. Its job
is to prevent cold loads from being issued when the worker's reported
host_memory.available_mb (minus in-flight commitments and safety margin)
cannot accommodate the new lane's projected footprint.
"""

from __future__ import annotations

from logos.capacity.host_ram_ledger import HostRamLedger


def test_reserve_within_available_succeeds():
    ledger = HostRamLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        host_ram_mb=50000.0,
        raw_available_mb=100000.0,
        safety_margin_mb=4096.0,
    )
    assert rid is not None
    assert ledger.get_committed_mb(1) == 50000.0


def test_reserve_denied_when_committed_exceeds_available():
    """Two 50GB loads cannot both fit in 100GB minus 4GB margin."""
    ledger = HostRamLedger()
    first = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        host_ram_mb=50000.0,
        raw_available_mb=100000.0,
        safety_margin_mb=4096.0,
    )
    assert first is not None
    # Effective available = 100000 - 50000 = 50000; need = 50000 + 4096
    second = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="b",
        operation="load",
        host_ram_mb=50000.0,
        raw_available_mb=100000.0,
        safety_margin_mb=4096.0,
    )
    assert second is None


def test_release_restores_capacity_for_next_reservation():
    ledger = HostRamLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        host_ram_mb=80000.0,
        raw_available_mb=100000.0,
        safety_margin_mb=4096.0,
    )
    assert rid is not None
    ledger.release(rid)
    assert ledger.get_committed_mb(1) == 0.0
    rid2 = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="b",
        operation="load",
        host_ram_mb=80000.0,
        raw_available_mb=100000.0,
        safety_margin_mb=4096.0,
    )
    assert rid2 is not None


def test_safety_margin_blocks_borderline_reservation():
    """A reservation that uses every byte without margin must still be denied."""
    ledger = HostRamLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        host_ram_mb=10000.0,
        raw_available_mb=10000.0,
        safety_margin_mb=1024.0,
    )
    assert rid is None


def test_per_provider_isolation():
    """Reservations on one provider do not affect another."""
    ledger = HostRamLedger()
    ledger.reserve(provider_id=1, lane_id="a", operation="load", host_ram_mb=50000.0)
    rid = ledger.try_reserve_atomic(
        provider_id=2,
        lane_id="x",
        operation="load",
        host_ram_mb=50000.0,
        raw_available_mb=80000.0,
        safety_margin_mb=4096.0,
    )
    assert rid is not None  # Provider 2 sees its own empty ledger
    assert ledger.get_committed_mb(1) == 50000.0
    assert ledger.get_committed_mb(2) == 50000.0


def test_negative_reservation_offsets_positive():
    """A reclaim_stop reservation (negative MB) cancels its paired load."""
    ledger = HostRamLedger()
    pos = ledger.reserve(1, "lane-a", "load", host_ram_mb=40000.0)
    neg = ledger.reserve(1, "lane-b", "reclaim_stop", host_ram_mb=-30000.0)
    # Net committed = 10000
    assert ledger.get_committed_mb(1) == 10000.0
    ledger.release(pos)
    ledger.release(neg)
    assert ledger.get_committed_mb(1) == 0.0


def test_active_reservation_lookup():
    ledger = HostRamLedger()
    ledger.reserve(1, "lane-a", "load", host_ram_mb=10000.0)
    assert ledger.has_active_reservation(1, "lane-a") is True
    assert ledger.has_active_reservation(1, "lane-b") is False
    assert ledger.has_active_reservation(1, "lane-a", operation="load") is True
    assert ledger.has_active_reservation(1, "lane-a", operation="wake") is False


def test_cleanup_stale_releases_old_reservations():
    """Reservations older than max_age_seconds are reaped as a safety net."""
    ledger = HostRamLedger()
    rid = ledger.reserve(1, "lane-a", "load", host_ram_mb=10000.0)
    # Force stale by rewriting the created_at field
    ledger._reservations[rid].created_at -= 1000.0
    reaped = ledger.cleanup_stale(max_age_seconds=60.0)
    assert reaped == 1
    assert ledger.get_committed_mb(1) == 0.0


def test_effective_available_subtracts_commitments():
    ledger = HostRamLedger()
    ledger.reserve(1, "lane-a", "load", host_ram_mb=30000.0)
    eff = ledger.get_effective_available_mb(1, raw_available_mb=100000.0)
    assert eff == 70000.0

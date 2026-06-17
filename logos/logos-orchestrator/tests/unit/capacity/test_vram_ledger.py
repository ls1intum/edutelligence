"""Tests for VRAMLedger atomic reservation gating.

Focus: per-GPU enforcement for both single-GPU (TP=1) and multi-GPU (TP>1)
placements.  The ledger must reject reservations that fit aggregate-wise but
fail on at least one targeted device — otherwise vLLM wakes can be approved
that OOM at runtime.
"""

from __future__ import annotations

from logos import VRAMLedger


def test_aggregate_check_denies_when_committed_exceeds_available():
    ledger = VRAMLedger()
    ledger.reserve(provider_id=1, lane_id="a", operation="load", vram_mb=20000.0)
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="b",
        operation="load",
        vram_mb=15000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
    )
    assert rid is None


def test_aggregate_check_passes_with_room():
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        vram_mb=10000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
    )
    assert rid is not None


def test_per_gpu_tp1_denies_when_target_device_full():
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="wake",
        vram_mb=8000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
        gpu_devices="0",
        per_gpu_free={0: 5000.0, 1: 25000.0},
    )
    assert rid is None  # GPU 0 has 5GB but lane needs 8GB


def test_per_gpu_tp1_passes_when_target_device_has_room():
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="wake",
        vram_mb=8000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
        gpu_devices="1",
        per_gpu_free={0: 5000.0, 1: 25000.0},
    )
    assert rid is not None


def test_per_gpu_tp2_denies_when_one_device_short():
    """Regression for the Mistral-wake OOM: aggregate fits but one rank doesn't.

    TP=2, total 14000MB → 7000MB per rank.  GPU 0 has 6000MB free; GPU 1
    has 25000MB.  Aggregate (31000MB) is fine, but per-rank GPU 0 fails.
    Pre-fix this slipped through because per-GPU was gated on
    `len(parsed_gpus) == 1`.
    """
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="mistral",
        operation="wake",
        vram_mb=14000.0,
        raw_available_mb=31000.0,
        safety_margin=1.0,
        gpu_devices="0,1",
        per_gpu_free={0: 6000.0, 1: 25000.0},
    )
    assert rid is None


def test_per_gpu_tp2_passes_when_balanced():
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="mistral",
        operation="wake",
        vram_mb=14000.0,
        raw_available_mb=20000.0,
        safety_margin=1.0,
        gpu_devices="0,1",
        per_gpu_free={0: 8000.0, 1: 8000.0},
    )
    assert rid is not None


def test_per_gpu_tp2_safety_margin_applied_per_rank():
    """safety_margin=1.1 on TP=2 with vram_mb=10000 → needs 5500/rank."""
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="wake",
        vram_mb=10000.0,
        raw_available_mb=20000.0,
        safety_margin=1.1,
        gpu_devices="0,1",
        per_gpu_free={0: 5500.0, 1: 5500.0},
    )
    assert rid is not None  # exact threshold

    ledger2 = VRAMLedger()
    rid2 = ledger2.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="wake",
        vram_mb=10000.0,
        raw_available_mb=20000.0,
        safety_margin=1.1,
        gpu_devices="0,1",
        per_gpu_free={0: 5499.0, 1: 5500.0},
    )
    assert rid2 is None  # 1MB short on GPU 0


def test_per_gpu_tp4_denies_when_one_of_four_short():
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        vram_mb=40000.0,
        raw_available_mb=80000.0,
        safety_margin=1.0,
        gpu_devices="0,1,2,3",
        per_gpu_free={0: 12000.0, 1: 12000.0, 2: 9000.0, 3: 12000.0},
    )
    assert rid is None  # GPU 2 short — needs 10000/rank


def test_per_gpu_subtracts_in_flight_commitments():
    """An in-flight TP=2 reservation on GPUs 0,1 must reduce per-GPU available
    for the next reservation."""
    ledger = VRAMLedger()
    rid1 = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        vram_mb=10000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
        gpu_devices="0,1",
        per_gpu_free={0: 8000.0, 1: 8000.0},
    )
    assert rid1 is not None

    # GPU 0 raw free = 8000, committed = 5000 from rid1, effective = 3000.
    # Second wake needs 4000/rank → DENY.
    rid2 = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="b",
        operation="wake",
        vram_mb=8000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
        gpu_devices="0,1",
        per_gpu_free={0: 8000.0, 1: 8000.0},
    )
    assert rid2 is None


def test_no_per_gpu_free_skips_per_gpu_check():
    """When the worker can't supply per_gpu_free, only the aggregate gate runs."""
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="wake",
        vram_mb=10000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
        gpu_devices="0,1",
        per_gpu_free=None,
    )
    assert rid is not None


def test_empty_gpu_devices_skips_per_gpu_check():
    """gpu_devices=None or empty string skips per-GPU enforcement."""
    ledger = VRAMLedger()
    rid = ledger.try_reserve_atomic(
        provider_id=1,
        lane_id="a",
        operation="load",
        vram_mb=10000.0,
        raw_available_mb=30000.0,
        safety_margin=1.0,
        gpu_devices=None,
        per_gpu_free={0: 1000.0, 1: 1000.0},
    )
    assert rid is not None

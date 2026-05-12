"""Weighted round-robin tie-break tests for ClassificationCorrectingScheduler.

When two logosnode workers tie on ``corrected_score`` (e.g. both warm with
the same model loaded and no queue), the scheduler picks one via weighted
random sampling — weights are each worker's ``gpu_performance_score``
(default 100). This file pins:

  - Weight 20 vs 40 → traffic splits ~1/3 vs ~2/3.
  - Equal weights (default 100) → ~50/50.
  - Reserved candidate is excluded; second-pick respects renormalised weights.
  - Non-tied entries keep their score-descending order.
  - Single-candidate list is unchanged.

Statistical tests use a fixed PRNG seed for reproducibility.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.ettft_estimator import EttftEstimate, ReadinessTier

# Reuse the mock infrastructure from the existing scheduler tests
from tests.unit.pipeline.test_correcting_scheduler import (
    MockAzureFacade,
    MockLogosNodeFacade,
    _make_scheduler,
)


def _warm(score: float, provider_id: int, model_id: int = 1) -> tuple:
    """Build a scored tuple shaped like _compute_candidate_scores output.

    Shape: (model_id, provider_id, provider_type, corrected_score,
            priority_int, ettft).
    """
    ettft = EttftEstimate(
        expected_wait_s=0.0,
        tier=ReadinessTier.WARM,
        reasoning="warm test",
        state_overhead_s=0.0,
    )
    return (model_id, provider_id, "logosnode", score, 1, ettft)


# ---------------------------------------------------------------------------
# Direct helper tests
# ---------------------------------------------------------------------------


class TestCandidateWeight:
    def test_default_score_is_100(self):
        scheduler = _make_scheduler()
        c = _warm(score=5.0, provider_id=42)
        assert scheduler._candidate_weight(c) == 100.0

    def test_custom_score_returned(self):
        logosnode = MockLogosNodeFacade()
        logosnode.set_gpu_performance_score(1, 20)
        logosnode.set_gpu_performance_score(2, 40)
        scheduler = _make_scheduler(logosnode=logosnode)
        assert scheduler._candidate_weight(_warm(5.0, 1)) == 20.0
        assert scheduler._candidate_weight(_warm(5.0, 2)) == 40.0

    def test_azure_falls_back_to_100(self):
        scheduler = _make_scheduler()
        ettft = EttftEstimate(
            expected_wait_s=0.0, tier=ReadinessTier.WARM,
            reasoning="azure",
        )
        azure_candidate = (1, 99, "azure", 5.0, 1, ettft)
        assert scheduler._candidate_weight(azure_candidate) == 100.0


class TestWeightedShuffleTied:
    def test_single_candidate_unchanged(self):
        scheduler = _make_scheduler()
        scored = [_warm(5.0, 1)]
        assert scheduler._weighted_shuffle_tied(scored) == scored

    def test_non_tied_groups_keep_order(self):
        """Candidates with different scores are not reordered between groups."""
        scheduler = _make_scheduler()
        a = _warm(5.0, 1)
        b = _warm(3.0, 2)
        c = _warm(1.0, 3)
        result = scheduler._weighted_shuffle_tied([a, b, c])
        # Scores were strictly descending and distinct → preserved exactly.
        assert [r[1] for r in result] == [1, 2, 3]

    def test_tied_within_zone_can_swap_order(self):
        """With two tied warm candidates and equal weight (default 100),
        many runs should produce both orderings."""
        scheduler = _make_scheduler()
        a = _warm(5.0, 1)
        b = _warm(5.0, 2)
        random.seed(0xC0FFEE)
        orderings = set()
        for _ in range(60):
            r = scheduler._weighted_shuffle_tied([a, b])
            orderings.add(tuple(c[1] for c in r))
        assert orderings == {(1, 2), (2, 1)}, (
            f"Expected both orderings to appear after shuffling; got {orderings}"
        )


class TestWeightedDistribution:
    """Statistical tests: over many trials, the first pick should match
    the configured weight ratios within tolerance."""

    NTRIALS = 6000
    TOLERANCE_FRACTION = 0.04  # ±4 %

    def _measure(self, scheduler, candidates):
        """Run the shuffle NTRIALS times and return Counter of first-pick provider_id."""
        random.seed(0xDEADBEEF)
        counter: Counter[int] = Counter()
        for _ in range(self.NTRIALS):
            ordered = scheduler._weighted_shuffle_tied(list(candidates))
            counter[ordered[0][1]] += 1
        return counter

    def test_default_weights_split_evenly(self):
        """Two providers, neither configured → both weight 100 → ~50/50."""
        scheduler = _make_scheduler()
        counts = self._measure(scheduler, [_warm(5.0, 1), _warm(5.0, 2)])
        for pid in (1, 2):
            assert abs(counts[pid] / self.NTRIALS - 0.5) < self.TOLERANCE_FRACTION, (
                f"provider {pid} share = {counts[pid] / self.NTRIALS:.3f}, expected ~0.5"
            )

    def test_20_vs_40_splits_one_third_two_thirds(self):
        """Provider 1 score=20, Provider 2 score=40 → 1/3 vs 2/3."""
        logosnode = MockLogosNodeFacade()
        logosnode.set_gpu_performance_score(1, 20)
        logosnode.set_gpu_performance_score(2, 40)
        scheduler = _make_scheduler(logosnode=logosnode)
        counts = self._measure(scheduler, [_warm(5.0, 1), _warm(5.0, 2)])
        assert abs(counts[1] / self.NTRIALS - 1 / 3) < self.TOLERANCE_FRACTION
        assert abs(counts[2] / self.NTRIALS - 2 / 3) < self.TOLERANCE_FRACTION

    def test_three_way_weighted_split(self):
        """Three workers with scores 10 / 20 / 70 → roughly 0.1 / 0.2 / 0.7."""
        logosnode = MockLogosNodeFacade()
        logosnode.set_gpu_performance_score(1, 10)
        logosnode.set_gpu_performance_score(2, 20)
        logosnode.set_gpu_performance_score(3, 70)
        scheduler = _make_scheduler(logosnode=logosnode)
        candidates = [_warm(5.0, 1), _warm(5.0, 2), _warm(5.0, 3)]
        counts = self._measure(scheduler, candidates)
        expected = {1: 0.10, 2: 0.20, 3: 0.70}
        for pid, target in expected.items():
            share = counts[pid] / self.NTRIALS
            assert abs(share - target) < self.TOLERANCE_FRACTION, (
                f"provider {pid}: expected ~{target}, got {share:.3f}"
            )

    def test_unbalanced_only_tied_zone_picks_weighted_first(self):
        """Mixed score list: only the top-tied zone is shuffled. The
        single non-tied candidate stays in its position regardless."""
        logosnode = MockLogosNodeFacade()
        logosnode.set_gpu_performance_score(1, 20)
        logosnode.set_gpu_performance_score(2, 40)
        scheduler = _make_scheduler(logosnode=logosnode)
        # Two tied at the top + one lower-scored.
        top1 = _warm(5.0, 1)
        top2 = _warm(5.0, 2)
        lower = _warm(2.0, 99)
        random.seed(0xBEEF)
        for _ in range(20):
            r = scheduler._weighted_shuffle_tied([top1, top2, lower])
            # The lower-scored candidate must always be at index 2.
            assert r[2] is lower
            # Top two must be one of (top1, top2) or (top2, top1)
            assert {r[0][1], r[1][1]} == {1, 2}


# ---------------------------------------------------------------------------
# End-to-end via _try_immediate_select
# ---------------------------------------------------------------------------


class TestImmediateSelectWeighted:
    """Higher-level test exercising the full select path. Reserves succeed
    on the chosen provider so we directly observe the first weighted pick."""

    NTRIALS = 2000
    TOLERANCE_FRACTION = 0.05

    def test_immediate_select_distributes_per_weights(self):
        logosnode = MockLogosNodeFacade()
        logosnode.set_gpu_performance_score(1, 20)
        logosnode.set_gpu_performance_score(2, 40)
        # Both reservations succeed (default True for any (mid, pid) not set)
        scheduler = _make_scheduler(logosnode=logosnode)
        candidates = [_warm(5.0, 1), _warm(5.0, 2)]

        random.seed(0xFACADE)
        counter: Counter[int] = Counter()
        for i in range(self.NTRIALS):
            # Pass a fresh copy each time (the function shuffles in place
            # via reassignment; defensive copy keeps the test pure).
            result = scheduler._try_immediate_select(list(candidates), f"req-{i}")
            assert result is not None
            picked_pid = result[1]
            counter[picked_pid] += 1
        assert abs(counter[1] / self.NTRIALS - 1 / 3) < self.TOLERANCE_FRACTION
        assert abs(counter[2] / self.NTRIALS - 2 / 3) < self.TOLERANCE_FRACTION

    def test_immediate_select_falls_through_if_chosen_denies(self):
        """If the weighted-picked candidate denies (try_reserve returns
        False), the next candidate gets a turn. Net result: the request
        still lands somewhere when at least one worker has capacity."""
        logosnode = MockLogosNodeFacade()
        logosnode.set_gpu_performance_score(1, 20)
        logosnode.set_gpu_performance_score(2, 40)
        # Worker 2 (the heavier weight) always denies — simulating its
        # parallel-capacity being exhausted. All traffic must end up on
        # worker 1 regardless of the weight bias.
        logosnode.set_reserve(1, 2, False)
        scheduler = _make_scheduler(logosnode=logosnode)
        candidates = [_warm(5.0, 1), _warm(5.0, 2)]

        random.seed(0xDEAD10CC)
        landings: Counter[int] = Counter()
        for i in range(200):
            result = scheduler._try_immediate_select(list(candidates), f"req-{i}")
            assert result is not None
            landings[result[1]] += 1
        # All requests must land on worker 1 — worker 2 always denies.
        assert landings[1] == 200
        assert landings[2] == 0
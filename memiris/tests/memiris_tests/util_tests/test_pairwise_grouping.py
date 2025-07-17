import itertools
import random
from typing import Any, List

import pytest

from memiris.util.grouping import check_groups, greedy_cover


def _all_pairs(blocks: List[List[Any]]) -> set[tuple[Any, Any]]:
    """Return the set of unordered pairs covered by *blocks*."""
    pairs: set[tuple[Any, Any]] = set()
    for g in blocks:
        pairs.update(tuple(sorted(p)) for p in itertools.combinations(g, 2))
    return pairs


@pytest.mark.parametrize(
    "v,k",
    [
        (2, 2),
        (5, 3),
        (10, 4),
        (20, 5),
        (30, 10),
        (50, 15),
        (100, 20),
        (200, 30),
        (500, 50),
    ],
)
def test_cover_with_ints(v: int, k: int) -> None:
    """All unordered pairs of integers must be covered and each block ≤ k."""
    items = list(range(v))
    blocks = greedy_cover(items, k)

    # 1) every unordered pair appears at least once
    expected = v * (v - 1) // 2
    assert len(_all_pairs(blocks)) == expected
    assert check_groups(blocks)

    # 2) no block exceeds k and no item repeats inside a block
    for g in blocks:
        assert len(g) <= k
        assert len(g) == len(set(g))


def test_cover_with_strings() -> None:
    """Same guarantees hold for non‑numeric item types (generic use‑case)."""
    items = [f"node_{i}" for i in range(12)]
    k = 4
    blocks = greedy_cover(items, k)

    assert len(_all_pairs(blocks)) == len(items) * (len(items) - 1) // 2
    assert check_groups(blocks)

    for g in blocks:
        assert len(g) <= k
        # ensure we actually got strings back
        assert all(isinstance(x, str) for x in g)


def test_deterministic_rng() -> None:
    """Using the same RNG seed must reproduce exactly the same cover."""
    items = list(range(15))
    k = 6
    seed = 20250622
    rng1 = random.Random(seed)
    rng2 = random.Random(seed)

    blocks1 = greedy_cover(items, k, rng=rng1)
    blocks2 = greedy_cover(items, k, rng=rng2)

    assert blocks1 == blocks2


def test_no_duplicate_blocks() -> None:
    """No two blocks should be identical."""
    items = list(range(18))
    k = 7
    blocks = greedy_cover(items, k)

    keys = [frozenset(b) for b in blocks]
    assert len(keys) == len(set(keys))


def test_handles_full_merge_case() -> None:
    """If k >= v the function must return a single block containing all items."""
    items = ["a", "b", "c", "d"]
    k = len(items)
    blocks = greedy_cover(items, k)

    assert blocks == [items]


def test_handles_empty_input() -> None:
    """An empty input should return an empty list."""
    items: List[Any] = []
    k = 3
    blocks = greedy_cover(items, k)

    assert blocks == []


def test_throws_on_invalid_k() -> None:
    """Should raise ValueError if k is less than 2 or greater than the number of items."""
    items = list(range(5))

    with pytest.raises(ValueError, match="need 2 ≤ k"):
        greedy_cover(items, 1)

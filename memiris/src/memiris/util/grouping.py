from __future__ import annotations

import itertools
import random
from typing import List, Sequence, Tuple, TypeVar

from langfuse._client.observe import observe

T = TypeVar("T")


def _bit(i: int) -> int:
    """
    Return a bit mask with the *i*-th bit set.
    Args:
        i: An integer representing the index of the bit to set (0-based).

    Returns:
        An integer with the *i*-th bit set to 1.
    """
    return 1 << i


def _pop_lsb(x: int) -> Tuple[int, int]:
    """
    Pop the least significant bit from *x* and return its index and the new value.
    Args:
        x: An integer from which to pop the least significant bit.

    Returns:
        A tuple containing the index of the least significant bit and the new value of *x* with that bit cleared.
    """
    lsb = x & -x
    idx = lsb.bit_length() - 1
    return idx, x ^ lsb


@observe(name="grouping.greedy_cover_max_groups")
def greedy_cover_max_groups(
    items: Sequence[T],
    k: int,
    max_groups: int,
    rng: random.Random | None = None,
) -> List[List[T]]:
    """
    Cover all unordered pairs of *items* with blocks of size ≤ *k*.

    Args:
        items: A sequence of items to be grouped.
        k: The maximum size of each group (block).
        max_groups: Optional maximum number of groups to return.
        rng: An optional random number generator for tie-breaking.

    Returns:
        A list of groups (blocks) where each group contains items that cover all other items in the group.
    """
    if max_groups is not None and max_groups < 1:
        raise ValueError("max_groups must be at least 1")

    groups: List[List[T]] = greedy_cover(items, k, rng=rng)
    while len(groups) > max_groups:
        k += 1
        groups = greedy_cover(items, k, rng=rng)

    return groups


@observe(name="grouping.greedy_cover")
def greedy_cover(
    items: Sequence[T],
    k: int,
    rng: random.Random | None = None,
) -> List[List[T]]:
    """
    Cover all unordered pairs of *items* with blocks of size ≤ *k*.

    Heuristics:
      1. greedy construction (bit‑sets, look‑ahead, tie‑breaking by RNG)
      2. backwards dominance cull
      3. iterative *merge* phase until no two blocks can be fused
    Args:
        items: A sequence of items to be grouped.
        k: The maximum size of each group (block).
        rng: An optional random number generator for tie-breaking.

    Returns:
        A list of groups (blocks) where each group contains items that cover all other items in the group.
    """
    if rng is None:
        rng = random.Random()

    items = list(items)
    v = len(items)
    if v == 0:
        return []
    elif v <= k:
        return [list(items)]
    elif not 2 <= k <= v:
        raise ValueError("need 2 ≤ k")

    # ---------- index maps & bit‑set state ---------------------------------
    ridx = items  # 0..v‑1 ➜ item

    full_mask = (1 << v) - 1
    uncovered_bits = [(full_mask ^ _bit(i)) for i in range(v)]
    degree = [v - 1] * v
    remaining = v * (v - 1) // 2

    bit_and = int.__and__
    bit_count = int.bit_count

    blocks: list[list[int]] = []
    seen_keys: set[frozenset[int]] = set()
    step = 0

    # ------------------ greedy construction -------------------------------
    while remaining:
        step += 1

        # 1️⃣ choose anchor with highest uncovered degree
        anchor = max(range(v), key=degree.__getitem__)

        # 2️⃣ choose best partner (break ties randomly)
        partner_candidates = []
        mask = uncovered_bits[anchor]
        while mask:
            j, mask = _pop_lsb(mask)
            partner_candidates.append((degree[j], j))
        if not partner_candidates:  # degenerate (shouldn't happen)
            partner_candidates = [(0, anchor)]
        best_deg = max(p for p, _ in partner_candidates)
        partners = [j for d, j in partner_candidates if d == best_deg]
        partner = rng.choice(partners)

        group_bits = _bit(anchor) | _bit(partner)
        group = [anchor, partner] if partner != anchor else [anchor]

        # 3️⃣ greedy grow with look‑ahead & RNG tie‑break
        while len(group) < k:
            best_gain = 0
            best_score = -1
            best_cands = []

            for cand in range(v):
                if group_bits & _bit(cand):
                    continue
                gain = bit_count(bit_and(uncovered_bits[cand], group_bits))
                if gain == 0:
                    continue
                horizon = degree[cand]
                score = (gain << 20) | horizon
                if score > best_score:
                    best_score, best_gain, best_cands = score, gain, [cand]
                elif score == best_score:
                    best_cands.append(cand)

            if best_gain == 0:
                break
            cand = rng.choice(best_cands)
            group_bits |= _bit(cand)
            group.append(cand)

        # 4️⃣ store canonical block (avoid duplicates)
        key = frozenset(group)
        if key not in seen_keys:
            seen_keys.add(key)
            blocks.append(group)

        # 5️⃣ mark newly covered pairs
        for i, j in itertools.combinations(group, 2):
            if uncovered_bits[i] & _bit(j):
                uncovered_bits[i] ^= _bit(j)
                uncovered_bits[j] ^= _bit(i)
                degree[i] -= 1
                degree[j] -= 1
                remaining -= 1

    # --------------- backwards dominance cull -----------------------------
    already: set[Tuple[int, int]] = set()
    pruned: list[list[int]] = []

    for g in reversed(blocks):
        pairs = {(min(a, b), max(a, b)) for a, b in itertools.combinations(g, 2)}
        if pairs.issubset(already):
            continue
        already.update(pairs)
        pruned.append(g)

    pruned.reverse()

    # --------------- iterative merge phase --------------------------------
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(pruned):
            j = i + 1
            while j < len(pruned):
                gi, gj = pruned[i], pruned[j]
                union = sorted(set(gi).union(gj))
                if len(union) <= k:
                    pruned[i] = union
                    pruned.pop(j)
                    changed = True
                    # do *not* increment j – new pruned[j] needs checking
                else:
                    j += 1
            i += 1

    # convert indices → original items
    result: List[List[T]] = [[ridx[p] for p in g] for g in pruned]

    return result


def check_groups(groups: list[list[T]]) -> bool:
    cnt: dict[T, list[T]] = {}
    for g in groups:
        for i in g:
            if i not in cnt:
                cnt[i] = []
            without_i = [x for x in g if x != i]
            for j in without_i:
                cnt[i].append(j)

    for i, js in cnt.items():
        if len(js) < len(cnt) - 1:
            return False

    return True

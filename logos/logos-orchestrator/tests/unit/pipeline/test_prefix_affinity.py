"""Tests for prefix-cache-aware stream identity and the affinity table.

Two properties carry the whole feature:

1. The serialized prefix is *append-only* — turn n+1 extends turn n's string
   rather than rewriting it — so consecutive turns of one conversation share
   their leading block hashes.
2. Identity is scoped to ``(api_key_id, prefix)``, never to a user, so a
   single key running several agent loops in parallel keeps them apart.
"""

from logos.pipeline.prefix_affinity import (
    PrefixAffinityRouter,
    affinity_keys,
    serialize_prefix,
)

BLOCK = 64  # small blocks keep the fixtures readable
LIMIT = BLOCK * 8


def _conversation(turns: int, *, system: str = "S" * 200) -> dict:
    messages = [{"role": "system", "content": system}]
    for index in range(turns):
        messages.append({"role": "user", "content": f"user turn {index} " + "u" * 100})
        messages.append({"role": "assistant", "content": f"assistant turn {index} " + "a" * 100})
    return {"messages": messages}


# ---------------------------------------------------------------------------
# serialize_prefix
# ---------------------------------------------------------------------------


def test_serialized_prefix_is_append_only_across_turns():
    """A longer conversation must literally start with the shorter one."""
    short = serialize_prefix(_conversation(2), limit=100_000)
    long = serialize_prefix(_conversation(3), limit=100_000)
    assert long.startswith(short)
    assert len(long) > len(short)


def test_serialized_prefix_keeps_preamble_before_messages():
    text = serialize_prefix(
        {"instructions": "be brief", "messages": [{"role": "user", "content": "hi"}]},
        limit=100_000,
    )
    assert text.index("be brief") < text.index("hi")


def test_serialized_prefix_respects_limit():
    text = serialize_prefix(_conversation(50), limit=LIMIT)
    assert len(text) == LIMIT


def test_serialized_prefix_handles_responses_api_input_list():
    text = serialize_prefix(
        {"input": [{"role": "user", "content": "responses api"}], "instructions": "sys"},
        limit=100_000,
    )
    assert "responses api" in text and "sys" in text


def test_serialized_prefix_of_non_dict_is_empty():
    assert serialize_prefix("not a payload", limit=LIMIT) == ""


# ---------------------------------------------------------------------------
# affinity_keys
# ---------------------------------------------------------------------------


def _keys(api_key_id, payload):
    return affinity_keys(api_key_id, payload, block_chars=BLOCK, max_blocks=8)


def test_keys_are_deepest_block_first():
    keys = _keys(7, _conversation(3))
    assert len(keys) == 8  # capped by max_blocks
    # Reversing gives the chain order; each entry is a distinct block hash.
    assert len(set(keys)) == len(keys)


def test_continued_conversation_shares_the_leading_blocks():
    """The next turn must still resolve to the same stream."""
    first = _keys(7, _conversation(2))
    second = _keys(7, _conversation(3))
    # Keys run deepest-first; the blocks the two turns share sit at the tail.
    assert set(first) & set(second), "no block survived the added turn"


def test_same_prefix_under_different_api_keys_never_collides():
    assert not set(_keys(1, _conversation(3))) & set(_keys(2, _conversation(3)))


def test_parallel_streams_under_one_key_separate_after_the_shared_preamble():
    """Same system prompt, different first user turn → different deep blocks."""
    stream_a = _conversation(3)
    stream_b = _conversation(3)
    stream_b["messages"][1] = {"role": "user", "content": "a completely different opening " + "x" * 100}

    keys_a = _keys(7, stream_a)
    keys_b = _keys(7, stream_b)
    assert keys_a[0] != keys_b[0], "deepest block must distinguish the two streams"


def test_no_keys_without_an_api_key():
    assert _keys(None, _conversation(3)) == []


def test_no_keys_for_a_prompt_shorter_than_one_block():
    assert _keys(7, {"messages": [{"role": "user", "content": "hi"}]}) == []


def test_no_keys_for_an_unreadable_payload():
    assert _keys(7, None) == []


# ---------------------------------------------------------------------------
# PrefixAffinityRouter
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_router_returns_the_recorded_worker():
    router = PrefixAffinityRouter(ttl_s=60, max_entries=100)
    router.record(1, ["deep", "shallow"], 42)
    assert router.lookup(1, ["deep", "shallow"]) == 42


def test_router_prefers_the_deepest_matching_block():
    """A longer shared prefix is the better signal — it wins over a
    shallower block that some other stream also matches."""
    router = PrefixAffinityRouter(ttl_s=60, max_entries=100)
    router.record(1, ["shallow"], 1)
    router.record(1, ["deep", "shallow"], 2)
    # Lookup order is deepest first; "deep" only maps to worker 2.
    assert router.lookup(1, ["deep", "shallow"]) == 2


def test_router_is_scoped_per_model():
    router = PrefixAffinityRouter(ttl_s=60, max_entries=100)
    router.record(1, ["k"], 42)
    assert router.lookup(2, ["k"]) is None


def test_router_entries_expire():
    clock = _Clock()
    router = PrefixAffinityRouter(ttl_s=60, max_entries=100, time_source=clock)
    router.record(1, ["k"], 42)
    clock.now += 61
    assert router.lookup(1, ["k"]) is None


def test_router_evicts_least_recently_used_entries():
    router = PrefixAffinityRouter(ttl_s=600, max_entries=2)
    router.record(1, ["a"], 1)
    router.record(1, ["b"], 2)
    router.lookup(1, ["a"])  # refresh "a"
    router.record(1, ["c"], 3)
    assert router.lookup(1, ["b"]) is None
    assert router.lookup(1, ["a"]) == 1
    assert router.lookup(1, ["c"]) == 3


def test_disabled_router_never_records_or_matches():
    router = PrefixAffinityRouter(enabled=False)
    router.record(1, ["k"], 42)
    assert router.lookup(1, ["k"]) is None
    assert router.enabled is False


def test_router_debug_state_reports_hit_rate():
    router = PrefixAffinityRouter(ttl_s=60, max_entries=10)
    router.record(1, ["k"], 42)
    router.lookup(1, ["k"])
    router.lookup(1, ["missing"])
    state = router.debug_state()
    assert state["entries"] == 1
    assert state["hits"] == 1
    assert state["misses"] == 1
    assert state["hit_rate"] == 0.5

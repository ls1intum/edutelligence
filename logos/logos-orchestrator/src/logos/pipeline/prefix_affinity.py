# src/logos/pipeline/prefix_affinity.py
"""Prefix-cache-aware routing: keep one stream of requests on one worker.

When the same model is deployed on several workers, Logos has so far spread
requests over them by corrected score with a random tie-break. For a coding
agent — a long system prompt plus a conversation that only grows at the tail —
that is the worst possible placement: every turn lands on whichever worker
happens to win the coin flip, and the engine's prefix cache (vLLM's
``enable_prefix_caching``) starts from scratch each time.

This module gives the scheduler a cheap way to recognise "this request
continues a stream I have seen before" and prefer the worker that already
holds the KV blocks for it.

Identity
--------
A stream is *not* a user and *not* an API key: one API key can drive many
agent loops in parallel. The identity used here is
``(api_key_id, the actual request prefix)``, hashed into a chain of
fixed-size blocks the same way an engine hashes its own prefix-cache blocks:

    block 1 = H(api_key_id ‖ text[0:B])
    block 2 = H(block 1    ‖ text[B:2B])
    …

Consecutive turns of one conversation share every block up to the point where
they diverge, so the deepest matching block identifies the stream. Two
conversations under the same key that share only a system prompt match on the
early blocks and separate as soon as their first user turns differ. The
api_key_id seed keeps different keys from ever sharing an entry.

Only whole blocks are hashed. The trailing partial block is dropped, exactly
as an engine drops its trailing partial block, so turn *n* and turn *n+1*
agree on the blocks they do produce.

The map is deliberately soft state: an in-memory TTL/LRU table. Losing it
costs one round of cache misses, nothing more.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def env_bool(name: str, default: bool) -> bool:
    # An unset *or empty* variable means "default": compose passes tuning
    # knobs through as "${VAR:-}", so empty is the normal "not configured".
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Master switch — turning this off restores the previous random placement.
AFFINITY_ENABLED = env_bool("LOGOS_PREFIX_AFFINITY_ENABLED", True)

# How long a (stream → worker) mapping stays useful. Roughly "how long the
# engine is likely to still hold those KV blocks"; a stream that goes quiet
# for longer than this has probably been evicted anyway.
AFFINITY_TTL_S = env_float("LOGOS_PREFIX_AFFINITY_TTL_S", 900.0)

# Hard cap on the table (LRU beyond it). 20k entries ≈ a few MB.
AFFINITY_MAX_ENTRIES = env_int("LOGOS_PREFIX_AFFINITY_MAX_ENTRIES", 20_000)

# Block granularity in characters (~4 chars/token, so ~256 tokens).
AFFINITY_BLOCK_CHARS = env_int("LOGOS_PREFIX_AFFINITY_BLOCK_CHARS", 1024)

# Only the first N blocks are tracked: they already identify the stream, and
# bounding them keeps hashing cost flat for very long conversations.
AFFINITY_MAX_BLOCKS = env_int("LOGOS_PREFIX_AFFINITY_MAX_BLOCKS", 32)

# Prompt-bearing fields that precede the conversation, in prompt order.
_PREAMBLE_FIELDS = ("instructions", "system", "tools")

# Field separators — control characters that cannot appear in JSON output.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"


def _canonical(value: Any) -> str:
    """Stable textual form of one payload fragment."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover — default=str covers ~everything
        return repr(value)


def serialize_prefix(payload: Any, limit: int) -> str:
    """Render the cacheable part of ``payload`` as an append-only string.

    Append-only is the whole point: adding a turn to a conversation must
    extend the string rather than rewrite it, so the block hashes of the
    previous turn survive. Each fragment is emitted as its own record — a
    single ``json.dumps`` of the message list would not qualify, because the
    closing bracket moves with every turn.

    Stops once ``limit`` characters are produced; callers only hash the
    first ``max_blocks`` blocks anyway, and prompts can carry megabytes of
    inline base64.
    """
    if not isinstance(payload, dict):
        return ""

    chunks: List[str] = []
    produced = 0

    def _append(kind: str, value: Any) -> bool:
        """Append one record; return False once the limit is reached."""
        nonlocal produced
        rendered = f"{kind}{_FIELD_SEP}{_canonical(value)}{_RECORD_SEP}"
        chunks.append(rendered)
        produced += len(rendered)
        return produced < limit

    for field in _PREAMBLE_FIELDS:
        value = payload.get(field)
        if value in (None, "", [], {}):
            continue
        if not _append(field, value):
            return "".join(chunks)[:limit]

    messages = payload.get("messages")
    if not isinstance(messages, list):
        responses_input = payload.get("input")
        messages = responses_input if isinstance(responses_input, list) else None

    if messages is not None:
        for message in messages:
            if not _append("msg", message):
                return "".join(chunks)[:limit]
    else:
        for field in ("input", "prompt"):
            value = payload.get(field)
            if isinstance(value, str) and value:
                if not _append(field, value):
                    return "".join(chunks)[:limit]

    return "".join(chunks)[:limit]


def affinity_keys(
    api_key_id: Optional[int],
    payload: Any,
    *,
    block_chars: int = AFFINITY_BLOCK_CHARS,
    max_blocks: int = AFFINITY_MAX_BLOCKS,
) -> List[str]:
    """Chained prefix-block hashes for one request, deepest block first.

    Returns an empty list when there is nothing to key on — no API key, an
    unreadable payload, or a prompt shorter than one block. An empty list
    means "no opinion": the scheduler routes exactly as it did before.
    """
    if api_key_id is None or block_chars <= 0 or max_blocks <= 0:
        return []

    text = serialize_prefix(payload, limit=block_chars * max_blocks)
    block_count = min(max_blocks, len(text) // block_chars)
    if block_count <= 0:
        return []

    hasher = hashlib.sha256()
    hasher.update(f"{api_key_id}\x00".encode("utf-8"))
    keys: List[str] = []
    for index in range(block_count):
        block = text[index * block_chars : (index + 1) * block_chars]
        hasher.update(block.encode("utf-8", "replace"))
        keys.append(hasher.hexdigest()[:32])

    keys.reverse()  # deepest (most specific) block first
    return keys


class PrefixAffinityRouter:
    """TTL/LRU map from prefix block → the worker that last served it.

    Thread-safe: the scheduler runs on the event loop but the SDI refresh and
    capacity planner threads may read the debug state concurrently.
    """

    def __init__(
        self,
        ttl_s: float = AFFINITY_TTL_S,
        max_entries: int = AFFINITY_MAX_ENTRIES,
        enabled: bool = AFFINITY_ENABLED,
        time_source=time.monotonic,
    ) -> None:
        self._ttl_s = float(ttl_s)
        self._max_entries = max(1, int(max_entries))
        self._enabled = bool(enabled)
        self._now = time_source
        # (model_id, block_key) -> (provider_id, expires_at); ordered by recency
        self._entries: "OrderedDict[Tuple[int, str], Tuple[int, float]]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def lookup(self, model_id: int, keys: Sequence[str]) -> Optional[int]:
        """Worker that last served the deepest matching prefix block, if any."""
        if not self._enabled or not keys:
            return None
        now = self._now()
        with self._lock:
            for key in keys:  # deepest block first — most specific match wins
                entry_key = (int(model_id), key)
                entry = self._entries.get(entry_key)
                if entry is None:
                    continue
                provider_id, expires_at = entry
                if expires_at <= now:
                    self._entries.pop(entry_key, None)
                    continue
                self._entries.move_to_end(entry_key)
                self._hits += 1
                return provider_id
            self._misses += 1
            return None

    def record(self, model_id: int, keys: Sequence[str], provider_id: Optional[int]) -> None:
        """Remember that ``provider_id`` served this stream."""
        if not self._enabled or not keys or provider_id is None:
            return
        expires_at = self._now() + self._ttl_s
        with self._lock:
            for key in keys:
                entry_key = (int(model_id), key)
                self._entries[entry_key] = (int(provider_id), expires_at)
                self._entries.move_to_end(entry_key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def debug_state(self) -> Dict[str, Any]:
        with self._lock:
            lookups = self._hits + self._misses
            return {
                "enabled": self._enabled,
                "entries": len(self._entries),
                "max_entries": self._max_entries,
                "ttl_s": self._ttl_s,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": (self._hits / lookups) if lookups else None,
            }

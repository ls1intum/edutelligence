"""Request-lifecycle timeout and retry settings.

``LOGOS_TIMEOUT_S``, when set (> 0), overrides every per-stage request timeout in
the orchestrator — scheduler queue-wait, execution-context resolve, and the
orchestrator↔worker stream timeout — so one value makes a request effectively
never time out. This is used by the benchmark to isolate scheduling/lane
behaviour from timeout-induced failures (set it to e.g. 86400). When unset or
non-positive, every call site keeps its own default and production behaviour is
unchanged.

The ``_LOGOSNODE_*`` constants are the execution-path settings of the logosnode
request path (read only in ``main.py``). They live here rather than in
``logosnode_snapshot.py`` because that module is pure shaping of worker
runtime snapshots; the one snapshot-side constant
(``_LOGOSNODE_STATS_STALE_AFTER_SECONDS``) stays with the helper that uses it.
"""

import math
import os
import time

_ENV = "LOGOS_TIMEOUT_S"


# Default end-to-end window a request may spend waiting for a lane before it
# is answered with a queue-timeout 429. Bounded to what a client actually
# waits for: the Claude Code idle watchdog (API_FORCE_IDLE_TIMEOUT) defaults
# to 300s, and the observed Client-disconnected failures while queued sit far
# below even that (p50 ≈ 61s, p90 ≈ 300s) — a 20-minute hold kept queue slots
# on behalf of callers that gave up minutes earlier. 280s stays inside the
# 300s watchdog, so the 429 + Retry-After reaches a caller that is still
# connected and can act on it.
#
# The window is a whole-request budget, not a queue-only one: it starts at
# request ingress and auth, the worker reconnect wait and classification all
# count against it (see ``remaining_queue_wait_s``), so the 429 cannot land
# after the client's watchdog already fired.
DEFAULT_QUEUE_WAIT_TIMEOUT_S = 280.0


def global_timeout_s(default: float) -> float:
    """Return the global request timeout if ``LOGOS_TIMEOUT_S`` is set, else ``default``."""
    raw = os.getenv(_ENV)
    if not raw or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def queue_wait_window_s(request_timeout_s: float | None = None) -> float:
    """The queue window a request may spend waiting for a lane.

    The default/global window bounds *every* request, including the unstamped
    ones (async jobs) that have no client budget to recompute. The request's
    own ``timeout_s`` — the value the client actually waits on — may only
    narrow that window, never widen it, so no request holds a queue slot past
    the window. A non-positive or invalid ``request_timeout_s`` is treated as
    absent, mirroring ``main._client_timeout_s``.
    """
    window = global_timeout_s(DEFAULT_QUEUE_WAIT_TIMEOUT_S)
    if request_timeout_s is None:
        return window
    try:
        value = float(request_timeout_s)
    except (TypeError, ValueError):
        return window
    return min(window, value) if value > 0 else window


def remaining_queue_wait_s(ingress_at: float | None, request_timeout_s: float | None = None) -> float | None:
    """Queue-wait budget left for a request that entered the orchestrator at
    ``ingress_at`` (a ``time.monotonic()`` stamp taken at request ingress).

    The budget is the client's whole-request window minus what has already
    been spent: auth, the worker reconnect wait and classification all happen
    before enqueue and count against it, so the scheduler may only wait with
    what is left. The window is the *smaller* of the request's own
    ``timeout_s`` — the value the client actually waits on — and the
    default/global window, so a request with a 30s timeout that already spent
    25s before reaching the queue may only wait 5s, not the full 30s on top.
    A non-positive or invalid ``request_timeout_s`` is treated as absent.
    Without an ingress stamp (async jobs, tests) there is no client
    watchdog to beat, so ``None`` is returned and the scheduler keeps
    the plain window.

    Call this immediately before the queue wait, not earlier: anything that
    runs in between (notably the scheduler's synchronous candidate scoring,
    whose SDI refreshes can each block on a 5s HTTP fetch) also spends
    client window, and only a wait-time recompute deducts it.
    """
    if ingress_at is None:
        return None
    return max(0.0, queue_wait_window_s(request_timeout_s) - (time.monotonic() - ingress_at))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Parse a non-negative float env var, falling back to ``default``.

    Runs at import time, so a malformed deployment value must never raise and
    take the whole module down. Non-numeric, empty/whitespace, non-finite
    (``inf``/``nan``) and negative values all fall back to ``default`` — a
    negative or infinite backoff would otherwise be consumed by
    ``asyncio.sleep`` and raise or hang there.
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value) or value < 0:
        return default
    return value


# max(1, ...): a fractional LOGOS_TIMEOUT_S (e.g. 0.5) must not floor to 0 and
# cause immediate timeouts — clamp to at least 1 second.
_LOGOSNODE_INFER_TIMEOUT_SECONDS = max(1, int(global_timeout_s(_env_int("LOGOSNODE_INFER_TIMEOUT_SECONDS", 120))))
_LOGOSNODE_STREAM_TIMEOUT_SECONDS = max(
    1,
    int(
        global_timeout_s(
            _env_int(
                "LOGOSNODE_STREAM_TIMEOUT_SECONDS",
                _LOGOSNODE_INFER_TIMEOUT_SECONDS,
            )
        )
    ),
)
# Transparent retry for a logosnode stream that fails BEFORE the first token is
# forwarded to the client (e.g. a just-woken level-1 lane whose vLLM engine was
# not yet serveable — the worker now fails cleanly before stream_start). Safe to
# re-dispatch because nothing has been sent downstream yet; bounded, with a small
# backoff so the lane finishes waking. Never retries once a token has streamed.
_LOGOSNODE_PRETOKEN_RETRIES = _env_int("LOGOSNODE_PRETOKEN_RETRIES", 3)
_LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S = _env_float("LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S", 1.0)

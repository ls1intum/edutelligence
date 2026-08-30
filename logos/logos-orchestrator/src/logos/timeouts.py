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

import os

_ENV = "LOGOS_TIMEOUT_S"


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


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


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
_LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S = float(os.getenv("LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S", "1.0") or 1.0)

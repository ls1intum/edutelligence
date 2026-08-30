"""Single global request-lifecycle timeout knob.

``LOGOS_TIMEOUT_S``, when set (> 0), overrides every per-stage request timeout in
the orchestrator — scheduler queue-wait, execution-context resolve, and the
orchestrator↔worker stream timeout — so one value makes a request effectively
never time out. This is used by the benchmark to isolate scheduling/lane
behaviour from timeout-induced failures (set it to e.g. 86400). When unset or
non-positive, every call site keeps its own default and production behaviour is
unchanged.
"""

import os

_ENV = "LOGOS_TIMEOUT_S"


# Default window a queued request may wait for a lane before it is answered
# with a queue-timeout 429. Bounded to what a client actually waits for: the
# Claude Code idle watchdog (API_FORCE_IDLE_TIMEOUT) defaults to 300s, and
# the observed Client-disconnected failures while queued sit far below even
# that (p50 ≈ 61s, p90 ≈ 300s) — a 20-minute hold kept queue slots on
# behalf of callers that gave up minutes earlier. 280s stays inside the 300s
# watchdog, so the 429 + Retry-After reaches a caller that is still
# connected and can act on it.
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

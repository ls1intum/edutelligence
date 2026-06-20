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

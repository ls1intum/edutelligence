"""Lightweight wall-clock span logging for latency analysis.

Emits one greppable log line per span so production logs can attribute
end-to-end chat latency to individual phases:

    Pipeline timing | pipeline=ChatPipeline span=agent_loop duration_ms=12345 elapsed_ms=13000

``elapsed_ms`` is the time since the pipeline run started, so the log lines
double as a timeline of the run.
"""

import time
from contextlib import contextmanager
from typing import Iterator, Optional

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


@contextmanager
def timed_span(
    pipeline: str, span: str, run_start: Optional[float] = None
) -> Iterator[None]:
    """Log the wall-clock duration of the wrapped block.

    Args:
        pipeline: Name of the pipeline the span belongs to.
        span: Name of the phase being measured.
        run_start: ``time.perf_counter()`` value of the pipeline run start;
            when given, the log line includes the total elapsed time as well.
    """
    span_start = time.perf_counter()
    try:
        yield
    finally:
        now = time.perf_counter()
        duration_ms = (now - span_start) * 1000
        if run_start is not None:
            logger.info(
                "Pipeline timing | pipeline=%s span=%s duration_ms=%.0f elapsed_ms=%.0f",
                pipeline,
                span,
                duration_ms,
                (now - run_start) * 1000,
            )
        else:
            logger.info(
                "Pipeline timing | pipeline=%s span=%s duration_ms=%.0f",
                pipeline,
                span,
                duration_ms,
            )

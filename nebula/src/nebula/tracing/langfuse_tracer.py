"""
Central LangFuse tracing module for Nebula.

Provides:
- trace_job() context manager for creating a parent trace per job
- trace_span() context manager for creating nested spans
- trace_generation() context manager for direct LLM API calls
- trace_subprocess() context manager for ffmpeg operations
- Proper parent-child nesting within job traces
"""

import logging
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies and allow graceful degradation
_langfuse_module = None
_langfuse_client: Optional[Any] = None
_is_initialized = False
_init_lock = threading.Lock()


def _get_langfuse_module():
    """Lazy load the langfuse module."""
    global _langfuse_module
    if _langfuse_module is None:
        try:
            # pylint: disable=import-outside-toplevel
            import langfuse  # type: ignore[import-not-found]

            _langfuse_module = langfuse
        except ImportError:
            logger.warning("langfuse package not installed, tracing disabled")
            _langfuse_module = False
    return _langfuse_module if _langfuse_module else None


def _is_enabled() -> bool:
    """Check if LangFuse tracing is enabled via environment variables."""
    return os.environ.get("LANGFUSE_ENABLED", "").lower() == "true"


def init_langfuse() -> Optional[Any]:
    """
    Initialize the LangFuse client from environment variables.

    Required env vars when enabled:
    - LANGFUSE_ENABLED=true
    - LANGFUSE_PUBLIC_KEY
    - LANGFUSE_SECRET_KEY
    - LANGFUSE_HOST (optional, defaults to cloud.langfuse.com)

    Should be called once at application startup.
    Thread-safe initialization using a lock.
    """
    global _langfuse_client, _is_initialized

    # Fast path: already initialized
    if _is_initialized:
        return _langfuse_client

    with _init_lock:
        # Double-check after acquiring lock
        if _is_initialized:
            return _langfuse_client

        _is_initialized = True

        if not _is_enabled():
            logger.info("LangFuse tracing is disabled")
            return None

        langfuse_mod = _get_langfuse_module()
        if not langfuse_mod:
            return None

        try:
            public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
            secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
            host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

            if not public_key or not secret_key:
                logger.error(
                    "LangFuse enabled but missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY"
                )
                return None

            _langfuse_client = langfuse_mod.Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
                sample_rate=1.0,
            )
            logger.info("LangFuse client initialized (host: %s)", host)
            return _langfuse_client
        except Exception as e:
            logger.error("Failed to initialize LangFuse: %s", e)
            return None


def get_langfuse_client() -> Optional[Any]:
    """Get the LangFuse client (initializes if needed)."""
    if _langfuse_client is None and not _is_initialized:
        init_langfuse()
    return _langfuse_client


def shutdown_langfuse():
    """Shutdown the LangFuse client (flushes and waits for background threads). Thread-safe."""
    global _langfuse_client, _is_initialized
    with _init_lock:
        if _langfuse_client:
            try:
                _langfuse_client.shutdown()
                logger.info("LangFuse client shutdown")
            except Exception as e:
                logger.error("Error shutting down LangFuse: %s", e)
            _langfuse_client = None
        _is_initialized = False


def flush():
    """Flush any pending traces to LangFuse."""
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.debug("Failed to flush LangFuse: %s", e)


@dataclass
class TracingContext:
    """
    Context object for propagating tracing metadata through the transcription pipeline.

    Holds the parent span for proper nesting.
    """

    # Core identifiers
    job_id: str  # UUID of the transcription job - used as session_id
    video_url: Optional[str] = None
    lecture_unit_id: Optional[int] = None

    # Pipeline phase tracking
    current_phase: Optional[str] = None  # "heavy" or "light"

    # LangFuse span hierarchy - enables proper parent-child nesting
    current_span: Optional[Any] = None  # Current span for nesting

    # Flexible fields
    tags: list[str] = field(default_factory=list)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def get_metadata(self) -> dict[str, Any]:
        """Build metadata dict for observations."""
        metadata: dict[str, Any] = {
            "pipeline": "transcription",
        }
        if self.video_url:
            metadata["video_url"] = self.video_url
        if self.lecture_unit_id:
            metadata["lecture_unit_id"] = self.lecture_unit_id
        if self.current_phase:
            metadata["phase"] = self.current_phase
        metadata.update(self.extra_metadata)
        return metadata


# Context variable for async-safe context propagation
# ContextVar works correctly with asyncio.to_thread() unlike threading.local()
_context_var: ContextVar[Optional[TracingContext]] = ContextVar(
    "tracing_context", default=None
)


def set_current_context(ctx: TracingContext) -> None:
    """Set the current tracing context for this async context."""
    _context_var.set(ctx)


def get_current_context() -> Optional[TracingContext]:
    """Get the current tracing context for this async context."""
    return _context_var.get()


def clear_current_context() -> None:
    """Clear the current tracing context."""
    _context_var.set(None)


@contextmanager
def trace_job(
    job_id: str,
    name: str = "Transcription Job",
    video_url: Optional[str] = None,
    lecture_unit_id: Optional[int] = None,
    tags: Optional[list[str]] = None,
):
    """
    Context manager for creating a parent trace for an entire job.

    All observations (spans, generations) created within this context
    will be nested under this trace.

    Args:
        job_id: Unique job identifier (used as session ID)
        name: Name of the trace
        video_url: Optional video URL for metadata
        lecture_unit_id: Optional lecture unit ID for metadata
        tags: Optional tags for the trace
    """
    ctx = TracingContext(
        job_id=job_id,
        video_url=video_url,
        lecture_unit_id=lecture_unit_id,
        tags=tags or ["transcription"],
    )

    client = get_langfuse_client()
    if not client or not _is_enabled():
        logger.debug("LangFuse disabled, proceeding without tracing")
        set_current_context(ctx)
        try:
            yield ctx
        finally:
            clear_current_context()
        return

    # Use LangFuse v3 API: start_as_current_span creates a trace
    try:
        with client.start_as_current_span(
            name=name,
            input={"video_url": video_url, "lecture_unit_id": lecture_unit_id},
            metadata=ctx.get_metadata(),
        ) as span:
            # Update trace metadata
            span.update_trace(
                session_id=job_id,
                tags=ctx.tags,
            )
            ctx.current_span = span
            set_current_context(ctx)

            try:
                yield ctx
                span.update(output={"status": "completed"})
            except Exception as e:
                span.update(output={"status": "error", "error": str(e)}, level="ERROR")
                raise
            finally:
                clear_current_context()

    except Exception as e:
        logger.warning("Failed to create LangFuse trace, proceeding without: %s", e)
        set_current_context(ctx)
        try:
            yield ctx
        finally:
            clear_current_context()
            flush()


@contextmanager
def trace_span(
    name: str,
    input_data: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
):
    """
    Context manager for creating a span nested under the current trace/span.

    Args:
        name: Name of the span (e.g., "Heavy Pipeline", "Light Pipeline")
        input_data: Optional input data for the span
        metadata: Additional metadata to attach
    """

    class SpanTracer:
        """Helper class for managing span lifecycle."""

        def __init__(self):
            self.span = None
            self.start_time = time.time()

        def set_output(self, output: dict[str, Any]):
            """Set the output for this span."""
            if self.span:
                try:
                    duration_ms = (time.time() - self.start_time) * 1000
                    self.span.update(
                        output={**output, "duration_ms": round(duration_ms, 2)}
                    )
                except Exception as e:
                    logger.debug("Failed to set span output: %s", e)

        def end(self, success: bool = True, error: Optional[str] = None):
            """End the span (for manual control)."""
            if self.span:
                try:
                    duration_ms = (time.time() - self.start_time) * 1000
                    output: dict[str, Any] = {
                        "success": success,
                        "duration_ms": round(duration_ms, 2),
                    }
                    if error:
                        output["error"] = error
                    self.span.update(
                        output=output,
                        level="ERROR" if not success else "DEFAULT",
                    )
                except Exception as e:
                    logger.debug("Failed to end span: %s", e)

    tracer = SpanTracer()
    ctx = get_current_context()

    # Always yield - tracing failures should never break the job
    if not ctx or not ctx.current_span or not _is_enabled():
        try:
            yield tracer
        finally:
            pass
        return

    try:
        combined_metadata = {**(metadata or {}), **ctx.get_metadata()}
        parent_span = ctx.current_span

        with parent_span.start_as_current_span(
            name=name,
            input=input_data,
            metadata=combined_metadata,
        ) as span:
            tracer.span = span
            previous_span = ctx.current_span
            ctx.current_span = span

            try:
                yield tracer
                # Auto-update with duration if not already set
                duration_ms = (time.time() - tracer.start_time) * 1000
                span.update(output={"duration_ms": round(duration_ms, 2)})
            finally:
                ctx.current_span = previous_span

    except Exception as e:
        logger.debug("Failed to create span '%s': %s", name, e)
        yield tracer


@contextmanager
def trace_generation(
    name: str,
    model: str,
    input_data: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
):
    """
    Context manager for tracing direct LLM API calls (not via LangChain).

    Creates a generation observation nested under the current span.

    Args:
        name: Name of the generation (e.g., "Whisper Transcription", "GPT Vision")
        model: Model identifier (e.g., "whisper-1", "gpt-4.1-mini")
        input_data: Input to the model (prompt, audio info, etc.)
        metadata: Additional metadata to attach
    """

    class GenerationTracer:
        """Helper class for managing LLM generation trace lifecycle."""

        def __init__(self):
            self.generation = None

        def end(
            self,
            output: Optional[Any] = None,
            usage: Optional[dict[str, int]] = None,
            error: Optional[str] = None,
        ):
            """End the generation trace with output and usage info."""
            if self.generation:
                try:
                    update_kwargs: dict[str, Any] = {}
                    if output is not None:
                        update_kwargs["output"] = output
                    if usage:
                        update_kwargs["usage_details"] = usage
                    if error:
                        update_kwargs["output"] = {"error": error}
                        update_kwargs["level"] = "ERROR"
                    if update_kwargs:
                        self.generation.update(**update_kwargs)
                except Exception as e:
                    logger.debug("Failed to end generation trace: %s", e)

    tracer = GenerationTracer()
    ctx = get_current_context()

    if not ctx or not ctx.current_span or not _is_enabled():
        yield tracer
        return

    try:
        combined_metadata = {**(metadata or {}), **ctx.get_metadata()}
        parent_span = ctx.current_span

        with parent_span.start_as_current_generation(
            name=name,
            model=model,
            input=input_data,
            metadata=combined_metadata,
        ) as generation:
            tracer.generation = generation
            yield tracer

    except Exception as e:
        logger.debug("Failed to create generation trace: %s", e)
        yield tracer


@contextmanager
def trace_subprocess(
    name: str,
    command: list[str],
    metadata: Optional[dict[str, Any]] = None,
):
    """
    Context manager for tracing subprocess calls (e.g., ffmpeg).

    Creates a span nested under the current span.

    Args:
        name: Name of the operation (e.g., "Download Video", "Extract Audio")
        command: The command list being executed
        metadata: Additional metadata (e.g., input/output paths)
    """

    class SubprocessTracer:
        """Helper class for managing subprocess trace lifecycle."""

        def __init__(self):
            self.span = None
            self.start_time = time.time()

        def end(
            self,
            success: bool = True,
            output: Optional[dict[str, Any]] = None,
            error: Optional[str] = None,
        ):
            """End the subprocess trace."""
            if self.span:
                try:
                    duration_ms = (time.time() - self.start_time) * 1000
                    end_output: dict[str, Any] = {
                        "success": success,
                        "duration_ms": round(duration_ms, 2),
                        **(output or {}),
                    }
                    if error:
                        end_output["error"] = error

                    self.span.update(
                        output=end_output,
                        level="ERROR" if not success else "DEFAULT",
                    )
                except Exception as e:
                    logger.debug("Failed to end subprocess trace: %s", e)
                finally:
                    self.span = None

    tracer = SubprocessTracer()
    ctx = get_current_context()

    if not ctx or not ctx.current_span or not _is_enabled():
        yield tracer
        return

    try:
        combined_metadata = {
            "command_preview": " ".join(command[:5])
            + ("..." if len(command) > 5 else ""),
            **(metadata or {}),
            **ctx.get_metadata(),
        }
        parent_span = ctx.current_span

        with parent_span.start_as_current_span(
            name=name,
            input={"command": command},
            metadata=combined_metadata,
        ) as span:
            tracer.span = span
            yield tracer

            # Auto-update with duration if not manually ended
            if tracer.span:
                duration_ms = (time.time() - tracer.start_time) * 1000
                span.update(output={"duration_ms": round(duration_ms, 2)})

    except Exception as e:
        logger.debug("Failed to create subprocess trace: %s", e)
        yield tracer

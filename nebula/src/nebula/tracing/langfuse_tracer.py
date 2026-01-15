"""
Central LangFuse tracing module for Nebula.

Provides:
- @observe decorator for automatic span tracing
- TracingContext for job metadata propagation
- trace_generation() context manager for direct LLM API calls
- trace_subprocess() context manager for ffmpeg operations
- Proper nesting within job sessions
"""

import logging
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

# Note: threading is still needed for _init_lock used in thread-safe initialization

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

    Simpler than Iris - focused on job-level context.
    """

    # Core identifiers
    job_id: str  # UUID of the transcription job - used as session_id
    video_url: Optional[str] = None
    lecture_unit_id: Optional[int] = None

    # Pipeline phase tracking
    current_phase: Optional[str] = None  # "heavy" or "light"

    # Flexible fields
    tags: list[str] = field(default_factory=list)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_langfuse_params(self) -> dict[str, Any]:
        """Convert to parameters for LangFuse trace/span creation."""
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

        return {
            "session_id": self.job_id,
            "tags": self.tags,
            "metadata": metadata,
        }

    def add_metadata(self, **kwargs) -> "TracingContext":
        """Add extra metadata and return self for chaining."""
        self.extra_metadata.update(kwargs)
        return self

    def add_tag(self, tag: str) -> "TracingContext":
        """Add a tag and return self for chaining."""
        if tag not in self.tags:
            self.tags.append(tag)
        return self


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


F = TypeVar("F", bound=Callable[..., Any])


def observe(
    name: Optional[str] = None,
    as_type: Optional[str] = None,
) -> Callable[[F], F]:
    """
    Decorator to trace a function with LangFuse.

    If LangFuse is disabled, acts as a pass-through (no overhead).
    Automatically inherits the current trace context for proper nesting.

    Args:
        name: Custom name for the span (defaults to function name)
        as_type: Type of observation - "span", "generation", "tool", etc.

    Example:
        @observe(name="Download Video")
        def download_video(url, path):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            langfuse_mod = _get_langfuse_module()
            if not langfuse_mod or not _is_enabled():
                return func(*args, **kwargs)

            try:
                langfuse_observe = langfuse_mod.observe
                observed_func = langfuse_observe(name=name, as_type=as_type)(func)
                return observed_func(*args, **kwargs)
            except Exception as e:
                logger.debug(
                    "LangFuse observe failed, executing without tracing: %s", e
                )
                return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


@contextmanager
def trace_generation(
    name: str,
    model: str,
    input_data: Optional[Any] = None,
    metadata: Optional[dict[str, Any]] = None,
):
    """
    Context manager for tracing direct LLM API calls (not via LangChain).

    Use this for Whisper API and GPT Vision calls.

    Args:
        name: Name of the generation (e.g., "Whisper Transcription", "GPT Vision")
        model: Model identifier (e.g., "whisper-1", "gpt-4.1-mini")
        input_data: Input to the model (prompt, audio info, etc.)
        metadata: Additional metadata to attach

    Example:
        with trace_generation("Whisper Chunk", "whisper-1", {"chunk": i}) as gen:
            response = requests.post(...)
            gen.end(output={"segments": len(segments)})

    Yields:
        GenerationTracer object with .end() method to finalize the trace
    """
    client = get_langfuse_client()
    ctx = get_current_context()

    class GenerationTracer:
        """Helper class for managing LLM generation trace lifecycle."""

        def __init__(self):
            self.generation = None

        def end(
            self,
            output: Optional[Any] = None,
            usage: Optional[dict[str, int]] = None,
            error: Optional[str] = None,
            level: str = "DEFAULT",
        ):
            """End the generation trace with output and usage info."""
            if self.generation:
                try:
                    end_kwargs: dict[str, Any] = {
                        "level": level,
                    }
                    if output is not None:
                        end_kwargs["output"] = output
                    if usage:
                        end_kwargs["usage"] = usage
                    if error:
                        end_kwargs["status_message"] = error
                        end_kwargs["level"] = "ERROR"
                    self.generation.end(**end_kwargs)
                except Exception as e:
                    logger.debug("Failed to end generation trace: %s", e)

    tracer = GenerationTracer()

    if not client or not _is_enabled():
        yield tracer
        return

    try:
        combined_metadata = {**(metadata or {})}
        if ctx:
            combined_metadata.update(ctx.to_langfuse_params().get("metadata", {}))

        tracer.generation = client.generation(
            name=name,
            model=model,
            input=input_data,
            metadata=combined_metadata,
            session_id=ctx.job_id if ctx else None,
            tags=ctx.tags if ctx else None,
        )
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

    Records the command, duration, and outcome.

    Args:
        name: Name of the operation (e.g., "Download Video", "Extract Audio")
        command: The command list being executed
        metadata: Additional metadata (e.g., input/output paths)

    Example:
        with trace_subprocess("Extract Audio", cmd, {"video": path}) as span:
            result = subprocess.run(cmd, ...)
            span.end(success=result.returncode == 0)

    Yields:
        SubprocessTracer object with .end() method to finalize the trace
    """
    client = get_langfuse_client()
    ctx = get_current_context()

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
                    end_output = {
                        "success": success,
                        "duration_ms": round(duration_ms, 2),
                        **(output or {}),
                    }
                    if error:
                        end_output["error"] = error

                    self.span.end(
                        output=end_output,
                        level="ERROR" if not success else "DEFAULT",
                    )
                except Exception as e:
                    logger.debug("Failed to end subprocess trace: %s", e)

    tracer = SubprocessTracer()

    if not client or not _is_enabled():
        yield tracer
        return

    try:
        combined_metadata = {
            # Truncate command for readability
            "command_preview": " ".join(command[:5])
            + ("..." if len(command) > 5 else ""),
            **(metadata or {}),
        }
        if ctx:
            combined_metadata.update(ctx.to_langfuse_params().get("metadata", {}))

        tracer.span = client.span(
            name=name,
            input={"command": command},
            metadata=combined_metadata,
            session_id=ctx.job_id if ctx else None,
            tags=ctx.tags if ctx else None,
        )
        yield tracer
    except Exception as e:
        logger.debug("Failed to create subprocess trace: %s", e)
        yield tracer

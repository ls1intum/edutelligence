"""
Central LangFuse tracing module for Pyris.

Provides:
- @observe decorator for automatic tracing
- TracingContext for rich metadata propagation
- Model name and token counts on model-call generations
- Proper nesting of sub-pipelines and tool calls
- TracedThreadPoolExecutor for correct trace nesting in threaded code
"""

import concurrent.futures
import contextvars
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

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
            import langfuse  # pylint: disable=import-outside-toplevel

            _langfuse_module = langfuse
        except ImportError:
            logger.warning("langfuse package not installed, tracing disabled")
            _langfuse_module = False
    return _langfuse_module if _langfuse_module else None


def _is_enabled() -> bool:
    """Check if LangFuse tracing is enabled."""
    # Import here to avoid circular dependency
    try:
        # pylint: disable=import-outside-toplevel
        from iris.config import settings

        return (
            hasattr(settings, "langfuse")
            and settings.langfuse is not None
            and settings.langfuse.enabled
        )
    except Exception:
        return False


def mask_callback_credentials(*, data: Any, **_kwargs) -> Any:
    """Langfuse mask: serialize the traced data as Langfuse would, then scrub callback tokens.

    Observed functions receive callback objects whose URL contains the callback token when an
    older Artemis sends no run id.
    """
    # pylint: disable=import-outside-toplevel
    from langfuse._utils.serializer import EventSerializer

    from iris.common.callback_token import scrub_callback_credentials

    return scrub_callback_credentials(json.loads(json.dumps(data, cls=EventSerializer)))


def init_langfuse() -> Optional[Any]:
    """
    Initialize the LangFuse client from settings.

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
            # pylint: disable=import-outside-toplevel
            from iris.config import settings

            _langfuse_client = langfuse_mod.Langfuse(
                public_key=settings.langfuse.public_key,
                secret_key=settings.langfuse.secret_key,
                host=settings.langfuse.host,
                environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
                sample_rate=1.0,  # 100% sampling as decided
                mask=mask_callback_credentials,
            )
            logger.info(
                "LangFuse client initialized successfully (host: %s)",
                settings.langfuse.host,
            )
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
    """Flush and shutdown the LangFuse client. Thread-safe."""
    global _langfuse_client, _is_initialized
    with _init_lock:
        if _langfuse_client:
            try:
                _langfuse_client.flush()
                logger.info("LangFuse client flushed and shutdown")
            except Exception as e:
                logger.error("Error shutting down LangFuse: %s", e)
            _langfuse_client = None
        _is_initialized = False


@dataclass
class TracingContext:
    """
    Context object for propagating tracing metadata through pipelines.

    Create at pipeline entry points and pass through to sub-components.
    All relevant IDs and names are captured for comprehensive observability.
    """

    # Core identifiers
    user_id: Optional[str] = None
    session_id: Optional[str] = None  # run id from Artemis

    # Course context
    course_id: Optional[int] = None
    course_name: Optional[str] = None

    # Exercise context
    exercise_id: Optional[int] = None
    exercise_title: Optional[str] = None
    exercise_type: Optional[str] = None

    # Lecture context
    lecture_id: Optional[int] = None
    lecture_name: Optional[str] = None
    lecture_unit_id: Optional[int] = None
    lecture_unit_name: Optional[str] = None

    # FAQ context
    faq_id: Optional[int] = None

    # Pipeline info
    pipeline_name: Optional[str] = None
    variant: Optional[str] = None
    artemis_base_url: Optional[str] = None

    # Flexible fields
    tags: list[str] = field(default_factory=list)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dto(
        cls, dto: Any, pipeline_name: str, variant: Optional[str] = None
    ) -> "TracingContext":
        """
        Create TracingContext from any pipeline DTO.

        Intelligently extracts all available metadata from the DTO structure.
        """
        ctx = cls(pipeline_name=pipeline_name, variant=variant)

        # Extract user info. Only the opaque Artemis id: names are personal data
        # that tracing does not need.
        if hasattr(dto, "user") and dto.user:
            ctx.user_id = str(dto.user.id)

        # Extract session/run ID and Artemis URL
        if hasattr(dto, "settings") and dto.settings:
            # The run id, never the callback token: traces leave Iris.
            ctx.session_id = getattr(dto.settings, "trace_run_id", None)
            ctx.artemis_base_url = getattr(dto.settings, "artemis_base_url", None)

        # Extract course info from CourseDTO
        if hasattr(dto, "course") and dto.course:
            ctx.course_id = getattr(dto.course, "id", None)
            ctx.course_name = getattr(dto.course, "name", None)

        # Extract exercise info
        exercise = getattr(dto, "programming_exercise", None) or getattr(
            dto, "text_exercise", None
        )
        if exercise:
            ctx.exercise_id = exercise.id
            ctx.exercise_title = exercise.title
            ctx.exercise_type = getattr(exercise, "type", None)

        # Extract lecture info
        if hasattr(dto, "lecture") and dto.lecture:
            ctx.lecture_id = getattr(dto.lecture, "id", None)
            ctx.lecture_name = getattr(dto.lecture, "title", None) or getattr(
                dto.lecture, "name", None
            )

        # Extract lecture unit info
        if hasattr(dto, "lecture_unit") and dto.lecture_unit:
            ctx.lecture_unit_id = getattr(dto.lecture_unit, "id", None)
            ctx.lecture_unit_name = getattr(dto.lecture_unit, "name", None) or getattr(
                dto.lecture_unit, "title", None
            )

        # Check for lecture units list (some DTOs have this)
        if hasattr(dto, "lecture_units") and dto.lecture_units:
            # Store count in extra metadata
            ctx.extra_metadata["lecture_units_count"] = len(dto.lecture_units)

        # Extract FAQ info
        if hasattr(dto, "faq") and dto.faq:
            ctx.faq_id = getattr(dto.faq, "id", None)

        # Build tags
        ctx.tags = [pipeline_name]
        if variant:
            ctx.tags.append(f"variant:{variant}")
        if ctx.exercise_type:
            ctx.tags.append(f"exercise_type:{ctx.exercise_type}")

        return ctx

    def to_langfuse_params(self) -> dict[str, Any]:
        """Convert to parameters for LangFuse trace/span updates."""
        metadata: dict[str, Any] = {
            "pipeline": self.pipeline_name,
        }

        # Add all available IDs and names
        if self.course_id:
            metadata["course_id"] = self.course_id
        if self.course_name:
            metadata["course_name"] = self.course_name

        if self.exercise_id:
            metadata["exercise_id"] = self.exercise_id
        if self.exercise_title:
            metadata["exercise_title"] = self.exercise_title
        if self.exercise_type:
            metadata["exercise_type"] = self.exercise_type

        if self.lecture_id:
            metadata["lecture_id"] = self.lecture_id
        if self.lecture_name:
            metadata["lecture_name"] = self.lecture_name
        if self.lecture_unit_id:
            metadata["lecture_unit_id"] = self.lecture_unit_id
        if self.lecture_unit_name:
            metadata["lecture_unit_name"] = self.lecture_unit_name

        if self.faq_id:
            metadata["faq_id"] = self.faq_id

        if self.variant:
            metadata["variant"] = self.variant

        # Add Artemis deep links
        if self.artemis_base_url:
            metadata["artemis_base_url"] = self.artemis_base_url
            if self.course_id:
                metadata["artemis_course_url"] = (
                    f"{self.artemis_base_url}/courses/{self.course_id}"
                )
                if self.exercise_id:
                    metadata["artemis_exercise_url"] = (
                        f"{self.artemis_base_url}/courses/{self.course_id}"
                        f"/exercises/{self.exercise_id}"
                    )
                if self.lecture_id:
                    metadata["artemis_lecture_url"] = (
                        f"{self.artemis_base_url}/courses/{self.course_id}"
                        f"/lectures/{self.lecture_id}"
                    )

        # Merge extra metadata
        metadata.update(self.extra_metadata)

        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
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


# ContextVar storage for current tracing context.
#
# Langfuse also stores its observation stack in ContextVars. Keeping Iris'
# tracing metadata in the same mechanism lets contextvars.copy_context()
# propagate both pieces of state across supported thread boundaries.
_current_context: contextvars.ContextVar[Optional[TracingContext]] = (
    contextvars.ContextVar("iris_tracing_context", default=None)
)


def set_current_context(ctx: TracingContext):
    """Set the current tracing context for this thread."""
    _current_context.set(ctx)


def get_current_context() -> Optional[TracingContext]:
    """Get the current tracing context for this thread."""
    return _current_context.get()


def clear_current_context():
    """Clear the current tracing context."""
    _current_context.set(None)


F = TypeVar("F", bound=Callable[..., Any])


_SENSITIVE_SCAN_DEPTH = 3


def _is_sensitive_here(value: Any) -> bool:
    settings = getattr(value, "settings", None)
    if settings is not None and getattr(settings, "authentication_token", None):
        return True
    # A status callback: it holds the run's bearer token as run_id.
    if getattr(value, "run_id", None) and hasattr(value, "url"):
        return True
    if getattr(value, "authentication_token", None):
        return True
    return bool(getattr(value, "first_name", None) or getattr(value, "last_name", None))


def _children(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, (str, bytes, int, float, bool)) or value is None:
        return []
    attributes = getattr(value, "__dict__", None)
    return list(attributes.values()) if isinstance(attributes, dict) else []


def _is_sensitive(value: Any, depth: int = _SENSITIVE_SCAN_DEPTH) -> bool:
    """Whether an argument holds a callback credential or student names.

    Langfuse serializes object attributes recursively, so execution states that
    carry the DTO or the callback a few levels down count as well.
    """
    if _is_sensitive_here(value):
        return True
    if depth <= 0:
        return False
    return any(_is_sensitive(child, depth - 1) for child in _children(value))


def carries_sensitive_data(args: tuple, kwargs: dict) -> bool:
    """Whether any argument of an observed call must not be exported as input."""
    return any(_is_sensitive(value) for value in (*args, *kwargs.values()))


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
        as_type: Type of observation - one of:
            - "span" (default): Generic span
            - "generation": LLM generation
            - "agent": Agent execution
            - "tool": Tool call
            - "chain": Chain execution
            - "retriever": Retrieval operation
            - "embedding": Embedding generation

    Example:
        @observe(name="My Pipeline")
        def my_pipeline(dto):
            ...

        @observe(name="LLM Call", as_type="generation")
        def call_llm(prompt):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Fast path: if langfuse not available or not enabled, just call func
            langfuse_mod = _get_langfuse_module()
            if not langfuse_mod or not _is_enabled():
                return func(*args, **kwargs)

            # Only fall back when tracing setup fails. Business exceptions from the
            # observed call must propagate without executing the function twice.
            try:
                langfuse_observe = langfuse_mod.observe
                # Arguments that carry the run's callback credential or student
                # names are not exported as the span input.
                capture_input = not carries_sensitive_data(args, kwargs)
                observed_func = langfuse_observe(
                    name=name, as_type=as_type, capture_input=capture_input
                )(func)
            except Exception as e:
                logger.debug(
                    "LangFuse observe failed, executing without tracing: %s", e
                )
                return func(*args, **kwargs)
            return observed_func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


class TracedThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor that propagates contextvars to child threads.

    The Langfuse SDK stores its observation stack in a ContextVar.
    Standard ThreadPoolExecutor does NOT copy contextvars to child threads,
    which causes @observe-decorated functions in those threads to create
    orphaned top-level traces instead of nesting under the parent.

    This executor copies the calling thread's context so that child threads
    inherit the Langfuse observation stack and produce properly nested traces.
    """

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)


def record_generation(model: Optional[str], usage: Any) -> None:
    """Add the model name and token counts to the current generation.

    Call it inside a function observed with ``as_type="generation"``; ``usage``
    is the call's TokenUsageDTO, or None when the provider sent none. Tracing
    errors are logged and never reach the model call.
    """
    if not _is_enabled():
        return
    client = get_langfuse_client()
    if client is None:
        return
    usage_details = None
    if usage is not None:
        usage_details = {
            "input": int(usage.num_input_tokens),
            "output": int(usage.num_output_tokens),
        }
    try:
        client.update_current_generation(model=model, usage_details=usage_details)
    except Exception as e:
        logger.debug("Failed to record the generation in LangFuse: %s", e)


def flush():
    """Flush any pending traces to LangFuse."""
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.debug("Failed to flush LangFuse: %s", e)

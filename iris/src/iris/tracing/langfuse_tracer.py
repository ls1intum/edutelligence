"""
Central LangFuse tracing module for Pyris.

Provides:
- @observe decorator for automatic tracing
- TracingContext for rich metadata propagation
- LangChain CallbackHandler integration
- Proper nesting of sub-pipelines and tool calls
"""

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
    session_id: Optional[str] = None  # authentication_token from Artemis

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

        # Extract user info
        if hasattr(dto, "user") and dto.user:
            ctx.user_id = str(dto.user.id)
            first_name = getattr(dto.user, "first_name", None)
            last_name = getattr(dto.user, "last_name", None)
            if first_name:
                ctx.extra_metadata["user_first_name"] = first_name
            if last_name:
                ctx.extra_metadata["user_last_name"] = last_name

        # Extract session/run ID and Artemis URL
        if hasattr(dto, "settings") and dto.settings:
            ctx.session_id = getattr(dto.settings, "authentication_token", None)
            ctx.artemis_base_url = getattr(dto.settings, "artemis_base_url", None)

        # Extract course info (handles both CourseDTO and ExtendedCourseDTO)
        if hasattr(dto, "course") and dto.course:
            ctx.course_id = getattr(dto.course, "id", None)
            ctx.course_name = getattr(dto.course, "name", None)

        # Extract exercise info
        if hasattr(dto, "exercise") and dto.exercise:
            ctx.exercise_id = getattr(dto.exercise, "id", None)
            ctx.exercise_title = getattr(dto.exercise, "title", None)
            ctx.exercise_type = getattr(dto.exercise, "type", None)

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


# Thread-local storage for current tracing context
_context_local = threading.local()


def set_current_context(ctx: TracingContext):
    """Set the current tracing context for this thread."""
    _context_local.context = ctx


def get_current_context() -> Optional[TracingContext]:
    """Get the current tracing context for this thread."""
    return getattr(_context_local, "context", None)


def clear_current_context():
    """Clear the current tracing context."""
    if hasattr(_context_local, "context"):
        delattr(_context_local, "context")


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

            # Delegate to LangFuse's observe decorator
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


# LangChain run names to filter out from traces (internal implementation noise)
FILTERED_RUN_NAMES = frozenset(
    {
        "RunnableLambda",
        "RunnablePassthrough",
        "RunnableAssign<agent_scratchpad>",
        "ChatPromptTemplate",
        "ToolsAgentOutputParser",
    }
)


class FilteringCallbackHandler:
    """
    Wrapper around Langfuse CallbackHandler that filters out noisy LangChain internals.

    Filters run names like RunnableSequence, RunnableAssign<agent_scratchpad>, etc.
    that clutter the trace without providing useful observability.
    """

    def __init__(self, handler: Any):
        self._handler = handler
        self._filtered_run_ids: set[str] = set()

    def _should_filter(self, serialized: Optional[dict], name: str) -> bool:
        """Check if this run should be filtered out."""
        if serialized is None:
            return name in FILTERED_RUN_NAMES if name else False
        run_name = name or serialized.get("name", "")
        # Also check the id field which sometimes contains the class name
        run_id = serialized.get("id", [])
        if run_id and isinstance(run_id, list) and len(run_id) > 0:
            last_id = run_id[-1]
            if last_id in FILTERED_RUN_NAMES:
                return True
        return run_name in FILTERED_RUN_NAMES

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        if self._should_filter(serialized, kwargs.get("name", "")):
            self._filtered_run_ids.add(str(run_id))
            return
        return self._handler.on_chain_start(serialized, inputs, run_id=run_id, **kwargs)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        if str(run_id) in self._filtered_run_ids:
            self._filtered_run_ids.discard(str(run_id))
            return
        return self._handler.on_chain_end(outputs, run_id=run_id, **kwargs)

    def on_chain_error(self, error, *, run_id, **kwargs):
        if str(run_id) in self._filtered_run_ids:
            self._filtered_run_ids.discard(str(run_id))
            return
        return self._handler.on_chain_error(error, run_id=run_id, **kwargs)

    def __getattr__(self, name):
        """Delegate all other methods to the wrapped handler."""
        return getattr(self._handler, name)


def get_langchain_callback() -> Optional[Any]:
    """
    Get a LangFuse CallbackHandler for LangChain integrations.

    The callback handler will automatically inherit the current trace context,
    ensuring LangChain operations are properly nested within the pipeline trace.

    Note: Trace attributes (user_id, session_id, tags, metadata) should be passed
    via the chain invoke config metadata using langfuse_ prefixed keys:
        config={
            "callbacks": [handler],
            "metadata": {
                "langfuse_user_id": "user-123",
                "langfuse_session_id": "session-456",
                "langfuse_tags": ["tag1", "tag2"],
            }
        }

    Returns:
        CallbackHandler if LangFuse is enabled, None otherwise.
        When None is returned, LangChain will work normally without tracing.
    """
    if not _is_enabled():
        return None

    langfuse_mod = _get_langfuse_module()
    if not langfuse_mod:
        return None

    try:
        # pylint: disable=import-outside-toplevel
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
        return FilteringCallbackHandler(handler)
    except Exception as e:
        logger.warning("Failed to create LangFuse CallbackHandler: %s", e)
        return None


def get_langchain_config(ctx: Optional[TracingContext] = None) -> dict[str, Any]:
    """
    Get a LangChain config dict with LangFuse callback and trace metadata.

    This is a convenience function that returns a complete config dict
    that can be passed to chain.invoke() or similar methods.

    Args:
        ctx: Optional TracingContext. If not provided, uses current thread's context.

    Returns:
        Config dict with callbacks and metadata for LangFuse tracing.
        Returns empty dict if LangFuse is disabled.

    Example:
        config = get_langchain_config(ctx)
        result = chain.invoke(input, config=config)
    """
    handler = get_langchain_callback()
    if not handler:
        return {}

    effective_ctx = ctx or get_current_context()

    config: dict[str, Any] = {"callbacks": [handler]}

    if effective_ctx:
        # LangFuse picks up these prefixed metadata keys automatically
        config["metadata"] = {
            "langfuse_user_id": effective_ctx.user_id,
            "langfuse_session_id": effective_ctx.session_id,
            "langfuse_tags": effective_ctx.tags,
            # Add custom metadata (non-prefixed keys are stored as regular metadata)
            **effective_ctx.to_langfuse_params().get("metadata", {}),
        }

    return config


def flush():
    """Flush any pending traces to LangFuse."""
    client = get_langfuse_client()
    if client:
        try:
            client.flush()
        except Exception as e:
            logger.debug("Failed to flush LangFuse: %s", e)

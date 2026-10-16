"""
LangFuse tracing module for Pyris.

Provides comprehensive observability for all AI pipeline runs with proper
nesting and metadata tracking.

Usage:
    # At application startup
    init_langfuse()

    # In pipelines - use @observe decorator
    @observe(name="My Pipeline")
    def my_pipeline(dto):
        ctx = TracingContext.from_dto(dto, "MyPipeline")
        set_current_context(ctx)
        # ... pipeline logic

    # In a model client - mark the call as a generation
    @observe(name="Model Call", as_type="generation")
    def chat(...):
        ...
        record_generation(model_name, response.token_usage)

    # At shutdown
    shutdown_langfuse()
"""

from iris.tracing.langfuse_tracer import (
    TracedThreadPoolExecutor,
    TracingContext,
    clear_current_context,
    get_current_context,
    get_langfuse_client,
    init_langfuse,
    observe,
    record_generation,
    set_current_context,
    shutdown_langfuse,
)

__all__ = [
    "TracedThreadPoolExecutor",
    "TracingContext",
    "clear_current_context",
    "get_current_context",
    "get_langfuse_client",
    "init_langfuse",
    "observe",
    "record_generation",
    "set_current_context",
    "shutdown_langfuse",
]

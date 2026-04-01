"""
LangFuse tracing module for Pyris.

Provides comprehensive observability for all AI pipeline runs with proper
nesting, metadata tracking, and LangChain integration.

Usage:
    # At application startup
    init_langfuse()

    # In pipelines - use @observe decorator
    @observe(name="My Pipeline")
    def my_pipeline(dto):
        ctx = TracingContext.from_dto(dto, "MyPipeline")
        set_current_context(ctx)
        # ... pipeline logic

    # For LangChain integrations
    callback = get_langchain_callback()
    chain.invoke(input, config={"callbacks": [callback]})

    # At shutdown
    shutdown_langfuse()
"""

from iris.tracing.langfuse_tracer import (
    TracedThreadPoolExecutor,
    TracingContext,
    clear_current_context,
    get_current_context,
    get_langchain_callback,
    get_langchain_config,
    get_langfuse_client,
    init_langfuse,
    observe,
    set_current_context,
    shutdown_langfuse,
)

__all__ = [
    "TracedThreadPoolExecutor",
    "TracingContext",
    "clear_current_context",
    "get_current_context",
    "get_langchain_callback",
    "get_langchain_config",
    "get_langfuse_client",
    "init_langfuse",
    "observe",
    "set_current_context",
    "shutdown_langfuse",
]

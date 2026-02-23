"""
LangFuse tracing module for Nebula transcription service.

Provides comprehensive observability for transcription jobs with proper
nesting, metadata tracking, and support for direct API calls and subprocess operations.

Usage:
    # At application startup (in app.py)
    init_langfuse()

    # Wrap entire job in trace_job for parent trace
    with trace_job(job_id, video_url=url, lecture_unit_id=lid) as ctx:
        # Use trace_span for major phases
        with trace_span("Heavy Pipeline"):
            # Subprocess calls nest under current span
            with trace_subprocess("Download Video", command) as sub:
                result = subprocess.run(command)
                sub.end(success=result.returncode == 0)

            # LLM calls nest under current span
            with trace_generation("Whisper", "whisper-1", input_data) as gen:
                response = api_call()
                gen.end(output=response)

    # At shutdown
    shutdown_langfuse()
"""

from nebula.tracing.langfuse_tracer import (
    TracingContext,
    clear_current_context,
    flush,
    get_current_context,
    get_langfuse_client,
    init_langfuse,
    set_current_context,
    shutdown_langfuse,
    trace_generation,
    trace_job,
    trace_span,
    trace_subprocess,
)

__all__ = [
    "TracingContext",
    "clear_current_context",
    "flush",
    "get_current_context",
    "get_langfuse_client",
    "init_langfuse",
    "set_current_context",
    "shutdown_langfuse",
    "trace_generation",
    "trace_job",
    "trace_span",
    "trace_subprocess",
]

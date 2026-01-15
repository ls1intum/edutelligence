"""
LangFuse tracing module for Nebula transcription service.

Provides comprehensive observability for transcription jobs with proper
nesting, metadata tracking, and support for direct API calls and subprocess operations.

Usage:
    # At application startup (in app.py)
    init_langfuse()

    # In worker - set context per job
    ctx = TracingContext(job_id=job_id, video_url=url, lecture_unit_id=lecture_unit_id)
    set_current_context(ctx)

    # Use decorators for function tracing
    @observe(name="Transcribe Audio")
    def transcribe_audio(...):
        ...

    # For direct API calls
    with trace_generation("Whisper", "whisper-1", input_data) as gen:
        response = api_call()
        gen.end(output=response)

    # For subprocess calls
    with trace_subprocess("ffmpeg", command) as span:
        result = subprocess.run(command)
        span.end(success=result.returncode == 0)

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
    observe,
    set_current_context,
    shutdown_langfuse,
    trace_generation,
    trace_subprocess,
)

__all__ = [
    "TracingContext",
    "clear_current_context",
    "flush",
    "get_current_context",
    "get_langfuse_client",
    "init_langfuse",
    "observe",
    "set_current_context",
    "shutdown_langfuse",
    "trace_generation",
    "trace_subprocess",
]

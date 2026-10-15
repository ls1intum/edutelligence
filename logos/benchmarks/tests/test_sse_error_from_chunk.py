"""HTTP 200 SSE error objects must populate RequestResult.error."""

import importlib.util
import sys
from pathlib import Path

_BM_PATH = Path(__file__).resolve().parent.parent / "benchmark_logos.py"
_spec = importlib.util.spec_from_file_location("benchmark_logos_sse_error", _BM_PATH)
bm = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bm
_spec.loader.exec_module(bm)


def test_openai_shaped_error_object():
    assert (
        bm._error_from_sse_chunk({"error": {"message": "context length exceeded", "type": "invalid_request_error"}})
        == "context length exceeded"
    )


def test_anthropic_shaped_error_event():
    assert (
        bm._error_from_sse_chunk({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        == "Overloaded"
    )


def test_plain_error_string():
    assert bm._error_from_sse_chunk({"error": "upstream reset"}) == "upstream reset"


def test_success_chunk_is_not_an_error():
    assert bm._error_from_sse_chunk({"choices": [{"delta": {"content": "hi"}}]}) is None

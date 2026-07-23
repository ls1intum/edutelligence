import logos as main
from logos.responses import extract_token_usage


def test_extract_token_usage_ignores_null_token_details():
    usage = {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
        "prompt_tokens_details": None,
        "completion_tokens_details": None,
    }

    assert extract_token_usage(usage) == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
    }


def test_extract_token_usage_skips_non_integer_fields():
    # Azure responses include a nested 'latency_checkpoint' dict in usage; it is
    # not a token count and must not reach the DB (would crash on insert).
    usage = {
        "prompt_tokens": 8,
        "completion_tokens": 1,
        "total_tokens": 9,
        "latency_checkpoint": {"engine_ttft_ms": 34, "total_duration_ms": 311},
        "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
    }

    assert extract_token_usage(usage) == {
        "prompt_tokens": 8,
        "completion_tokens": 1,
        "total_tokens": 9,
        "prompt_cached_tokens": 0,
        "prompt_audio_tokens": 0,
        "completion_reasoning_tokens": 0,
    }


def test_extract_token_usage_normalizes_responses_api_names():
    # The Responses API reports input/output tokens; billing and rate limiting
    # are keyed to the Chat Completions names.
    usage = {
        "input_tokens": 36,
        "output_tokens": 87,
        "total_tokens": 123,
        "input_tokens_details": {"cached_tokens": 24},
        "output_tokens_details": {"reasoning_tokens": 64},
    }

    assert extract_token_usage(usage) == {
        "prompt_tokens": 36,
        "completion_tokens": 87,
        "total_tokens": 123,
        "prompt_cached_tokens": 24,
        "completion_reasoning_tokens": 64,
    }


def test_extract_token_usage_keeps_fractional_whisper_duration():
    assert extract_token_usage({"type": "duration", "seconds": 9.125}) == {"audio_milliseconds": 9125}


def test_usage_extraction_falls_back_to_verbose_audio_duration():
    assert main._usage_tokens_from_payload({"duration": 2.001, "text": "hello"}) == {"audio_milliseconds": 2001}

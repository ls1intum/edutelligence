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

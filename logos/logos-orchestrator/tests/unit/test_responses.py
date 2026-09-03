import logos as main
from logos.responses import _CANONICAL_USAGE_FIELDS, extract_service_tier, extract_token_usage


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
    assert main._usage_tokens_from_payload({"duration": 2.001, "text": "hello"}) == {
        "audio_milliseconds": 2001,
        "billed_requests": 1,
    }


def test_usage_extraction_accepts_vllm_verbose_audio_string_duration():
    assert main._usage_tokens_from_payload({"duration": "3.3596875", "text": "hello"}) == {
        "audio_milliseconds": 3360,
        "billed_requests": 1,
    }


def test_extract_token_usage_normalizes_anthropic_messages():
    out = extract_token_usage(
        {
            "input_tokens": 200,
            "output_tokens": 400,
            "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 150,
        }
    )
    assert out == {
        "prompt_tokens": 200,
        "completion_tokens": 400,
        "prompt_cached_tokens": 800,
        "prompt_cache_write_tokens": 150,
    }


def test_extract_token_usage_normalizes_anthropic_cache_creation_breakdown():
    out = extract_token_usage(
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": 150,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 100,
                "ephemeral_1h_input_tokens": 50,
            },
        }
    )
    assert out["prompt_cache_write_tokens"] == 100
    assert out["prompt_cache_write_1h_tokens"] == 50


def test_extract_token_usage_normalizes_bedrock_converse_camelcase():
    out = extract_token_usage(
        {
            "inputTokens": 20,
            "outputTokens": 7,
            "cacheReadInputTokens": 5,
            "cacheWriteInputTokens": 3,
        }
    )
    assert out == {
        "prompt_tokens": 20,
        "completion_tokens": 7,
        "prompt_cached_tokens": 5,
        "prompt_cache_write_tokens": 3,
    }


def test_extract_token_usage_normalizes_deepseek_hit_miss():
    out = extract_token_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
        }
    )
    assert out["prompt_cached_tokens"] == 60
    assert out["prompt_cache_miss_tokens"] == 40


def test_extract_token_usage_normalizes_image_and_cached_audio_details():
    out = extract_token_usage(
        {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "cache_read_input_audio_tokens": 4,
            "cache_creation_input_audio_tokens": 2,
            "prompt_tokens_details": {"image_tokens": 5},
            "completion_tokens_details": {"image_tokens": 3},
        }
    )
    assert out["prompt_cache_read_audio_tokens"] == 4
    assert out["prompt_cache_write_audio_tokens"] == 2
    assert out["prompt_image_tokens"] == 5
    assert out["completion_image_tokens"] == 3


def test_extract_token_usage_logs_unknown_field(caplog):
    with caplog.at_level("INFO"):
        extract_token_usage({"prompt_tokens": 1, "completion_tokens": 1, "brand_new_widget_tokens": 9})
    assert "brand_new_widget_tokens" in caplog.text


def test_known_usage_vocabulary_is_pinned():
    assert _CANONICAL_USAGE_FIELDS == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cached_tokens",
        "prompt_cache_write_tokens",
        "prompt_cache_write_1h_tokens",
        "prompt_cache_miss_tokens",
        "prompt_audio_tokens",
        "prompt_image_tokens",
        "prompt_cache_read_audio_tokens",
        "prompt_cache_write_audio_tokens",
        "completion_reasoning_tokens",
        "completion_audio_tokens",
        "completion_image_tokens",
        "audio_milliseconds",
    }


def test_extract_service_tier():
    assert extract_service_tier({"service_tier": "Flex"}) == "flex"
    assert extract_service_tier({"choices": []}) is None
    assert extract_service_tier(None) is None

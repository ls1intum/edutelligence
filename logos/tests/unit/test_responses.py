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

from logos.billing.finalize import finalize_billing_inputs


def test_finalize_merges_usage_quantities_and_tier():
    req = {"messages": [{"role": "user", "content": "hello there"}]}
    resp = {
        "service_tier": "flex",
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        "choices": [{"message": {"content": "hi"}}],
    }
    usage, tier = finalize_billing_inputs(req, resp, "v1/chat/completions")
    assert tier == "flex"
    assert usage["prompt_tokens"] == 5
    assert usage["completion_tokens"] == 2
    assert usage["billed_requests"] == 1
    assert usage["billed_input_characters"] == len("hello there")
    assert usage["billed_output_characters"] == len("hi")


def test_finalize_no_usage_object_still_returns_request_quantity():
    usage, tier = finalize_billing_inputs({}, {"choices": []}, "v1/chat/completions")
    assert usage == {"billed_requests": 1}
    assert tier is None


def test_finalize_binary_output_keeps_request_derived_media_duration():
    usage, tier = finalize_billing_inputs(
        {"duration": 1.25},
        b"binary media",
        "v1/audio/speech",
    )
    assert usage == {"billed_requests": 1, "billed_output_milliseconds": 1250}
    assert tier is None


def test_finalize_rejects_raw_billed_namespace_key():
    resp = {"usage": {"prompt_tokens": 5, "completion_tokens": 2, "billed_requests": 99}}
    usage, _ = finalize_billing_inputs({}, resp, "v1/chat/completions")
    # A provider-supplied billed_* key is dropped; the locally derived count wins.
    assert usage["billed_requests"] == 1
    assert usage["prompt_tokens"] == 5
    assert usage["completion_tokens"] == 2


def test_finalize_verbose_audio_duration_matches_stored_billing_input():
    usage, tier = finalize_billing_inputs(
        {"file": "audio"},
        {"text": "transcribed", "duration": "3.3596875"},
        "v1/audio/transcriptions",
    )
    assert usage == {"audio_milliseconds": 3360, "billed_requests": 1}
    assert tier is None

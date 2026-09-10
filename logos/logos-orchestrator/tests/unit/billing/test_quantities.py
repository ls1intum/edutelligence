from logos.billing.quantities import derive_billable_quantities


def test_requests_always_one():
    q = derive_billable_quantities({}, {}, "v1/chat/completions")
    assert q["billed_requests"] == 1


def test_character_counts_and_images_for_chat():
    req = {
        "messages": [
            {"role": "user", "content": "hello"},  # 5
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi"},  # 2
                    {"type": "image_url", "image_url": {"url": "x"}},
                ],
            },
        ]
    }
    resp = {"choices": [{"message": {"content": "world!"}}]}  # 6
    q = derive_billable_quantities(req, resp, "v1/chat/completions")
    assert q["billed_input_characters"] == 7
    assert q["billed_output_characters"] == 6
    assert q["billed_input_images"] == 1


def test_output_characters_from_reconstructed_streaming_chat_completions():
    # The streaming accumulator rebuilds a Chat Completions payload with the
    # full text under choices[0].delta.content, not .message.
    resp = {"choices": [{"delta": {"content": "streamed reply"}}]}
    q = derive_billable_quantities({}, resp, "v1/chat/completions")
    assert q["billed_output_characters"] == len("streamed reply")


def test_output_characters_counted_once_when_message_and_delta_both_present():
    resp = {"choices": [{"message": {"content": "final"}, "delta": {"content": "final"}}]}
    q = derive_billable_quantities({}, resp, "v1/chat/completions")
    assert q["billed_output_characters"] == len("final")


def test_output_characters_from_anthropic_root_content():
    # Anthropic Messages: text at the payload root, list of parts when sync,
    # a plain string when reconstructed from a stream.
    assert derive_billable_quantities({}, {"content": "hi there"}, "v1/messages")["billed_output_characters"] == len(
        "hi there"
    )
    sync = {"content": [{"type": "text", "text": "abc"}, {"type": "tool_use", "id": "x"}]}
    assert derive_billable_quantities({}, sync, "v1/messages")["billed_output_characters"] == 3


def test_responses_nested_input_counts_characters_and_images():
    req = {
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "hello"},
                    {"type": "input_image", "image_url": "data:image/png;base64,x"},
                ],
            }
        ]
    }
    q = derive_billable_quantities(req, {}, "v1/responses")
    assert q["billed_input_characters"] == 5
    assert q["billed_input_images"] == 1


def test_explicit_input_image_dimensions_are_billed_without_guessing():
    req = {
        "input": [
            {
                "content": [
                    {"type": "input_image", "image_url": "x", "width": 640, "height": 480},
                    {"type": "input_image", "image_url": "y", "size": "128x256"},
                    {"type": "input_image", "image_url": "unknown"},
                ]
            }
        ]
    }
    q = derive_billable_quantities(req, {}, "v1/responses")
    assert q["billed_input_pixels"] == 640 * 480 + 128 * 256


def test_image_generation_pixels():
    req = {"prompt": "a cat", "size": "1024x1024", "n": 2}
    q = derive_billable_quantities(req, {"data": [{}, {}]}, "v1/images/generations")
    assert q["billed_output_pixels"] == 1024 * 1024 * 2
    assert q["billed_output_images"] == 2
    assert "billed_input_pixels" not in q


def test_image_generation_partial_response_prices_returned_count():
    # Two images requested, one returned: bill one image and one image's pixels.
    req = {"prompt": "a cat", "size": "512x512", "n": 2}
    q = derive_billable_quantities(req, {"data": [{}]}, "v1/images/generations")
    assert q["billed_output_images"] == 1
    assert q["billed_output_pixels"] == 512 * 512


def test_image_generation_empty_response_has_no_image_keys():
    req = {"prompt": "a cat", "size": "512x512", "n": 2}
    q = derive_billable_quantities(req, {"data": []}, "v1/images/generations")
    assert "billed_output_images" not in q
    assert "billed_output_pixels" not in q


def test_image_variations_are_billed_as_output_images():
    # DALL-E 2 /v1/images/variations: no prompt, an input image, and its sole
    # catalogue rate (input_cost_per_image) is stored as billed_output_images
    # for image-generation models. Without variations in the path check the
    # returned images would be entirely unbilled.
    req = {"size": "1024x1024", "n": 2}
    q = derive_billable_quantities(req, {"data": [{}, {}]}, "v1/images/variations")
    assert q["billed_output_images"] == 2
    assert q["billed_output_pixels"] == 1024 * 1024 * 2
    assert "billed_input_characters" not in q


def test_ocr_pages():
    q = derive_billable_quantities({}, {"pages": [{}, {}, {}]}, "v1/ocr")
    assert q["billed_ocr_pages"] == 3
    assert "billed_ocr_credits" not in q


def test_embedded_png_dimensions_are_billed_without_network_fetch():
    # Billing needs only PNG's signature and IHDR dimensions; pixel decoding is
    # deliberately avoided so malformed/compressed payloads cannot exhaust RAM.
    import base64

    header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (3).to_bytes(4, "big") + (2).to_bytes(4, "big")
    encoded = base64.b64encode(header).decode("ascii")
    q = derive_billable_quantities(
        {"messages": [{"content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}]}]},
        {},
        "v1/chat/completions",
    )
    assert q["billed_input_pixels"] == 6


def test_annotation_pages():
    q = derive_billable_quantities(
        {"document_annotation_format": {"type": "json_schema"}},
        {"pages": [{}, {}]},
        "v1/ocr",
    )
    assert q["billed_annotation_pages"] == 2


def test_web_search_queries_counted():
    resp = {"output": [{"type": "web_search_call"}, {"type": "message"}, {"type": "web_search_call"}]}
    q = derive_billable_quantities({}, resp, "v1/responses")
    assert q["billed_search_queries"] == 2


def test_web_search_counts_provider_reported_queries():
    resp = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"queries": ["one", "two", "three"]},
            }
        ]
    }
    assert derive_billable_quantities({}, resp, "v1/responses")["billed_search_queries"] == 3


def test_web_search_preserves_requested_context_size():
    req = {"tools": [{"type": "web_search_preview", "search_context_size": "high"}]}
    resp = {"output": [{"type": "web_search_call"}]}
    assert derive_billable_quantities(req, resp, "v1/responses")["billed_search_queries_high"] == 1


def test_web_search_also_records_one_prompt_without_losing_query_count():
    resp = {
        "output": [
            {
                "type": "web_search_call",
                "action": {"queries": ["one", "two", "three"]},
            }
        ]
    }
    q = derive_billable_quantities({}, resp, "v1/responses")
    assert q["billed_search_queries"] == 3
    assert q["billed_search_prompts"] == 1


def test_generated_video_duration_is_billed_in_milliseconds():
    assert derive_billable_quantities({"duration": "5.5"}, {}, "v1/videos")["billed_output_milliseconds"] == 5500


def test_generated_video_resolution_uses_specific_duration_quantity():
    q = derive_billable_quantities({"duration": 5, "resolution": "1080p"}, {}, "v1/videos")
    assert q == {"billed_requests": 1, "billed_output_milliseconds_1080p": 5000}


def test_explicit_input_video_duration_is_billed():
    q = derive_billable_quantities(
        {"input": [{"content": [{"type": "input_video", "durationSeconds": 2.25}]}]}, {}, "v1/embeddings"
    )
    assert q["billed_input_video_milliseconds"] == 2250


def test_input_video_duration_records_applicable_interval_tiers():
    q = derive_billable_quantities({"input": [{"type": "input_video", "duration": 16}]}, {}, "v1/embeddings")
    assert q["billed_input_video_milliseconds"] == 16_000
    assert q["billed_input_video_milliseconds_above_8s"] == 16_000
    assert q["billed_input_video_milliseconds_above_15s"] == 16_000


def test_native_gemini_maps_queries_are_billed():
    req = {"tools": [{"type": "google_maps"}]}
    resp = {"candidates": [{"groundingMetadata": {"webSearchQueries": ["a", "b"]}}]}
    assert derive_billable_quantities(req, resp, "v1/models/x:generateContent")["billed_google_maps_queries"] == 2


def test_container_creation_is_one_code_interpreter_session():
    assert (
        derive_billable_quantities({}, {"id": "container_1", "object": "container"}, "v1/containers")[
            "billed_code_interpreter_sessions"
        ]
        == 1
    )


def test_listing_containers_is_not_a_new_code_interpreter_session():
    # GET /v1/containers returns a list envelope, not a freshly created container.
    resp = {"object": "list", "data": [{"id": "container_1"}, {"id": "container_2"}]}
    assert "billed_code_interpreter_sessions" not in derive_billable_quantities({}, resp, "v1/containers")


def test_bedrock_guardrail_policy_units_are_billed_separately():
    q = derive_billable_quantities(
        {},
        {
            "usage": {
                "contentPolicyUnits": 2,
                "topicPolicyUnits": 3,
                "wordPolicyUnits": 0,
            }
        },
        "v1/guardrail",
    )
    assert q["billed_guardrail_contentPolicyUnits"] == 2
    assert q["billed_guardrail_topicPolicyUnits"] == 3
    assert "billed_guardrail_wordPolicyUnits" not in q


def test_generated_speech_prefers_realized_response_duration():
    assert (
        derive_billable_quantities({"duration": 10}, {"duration": 2.125}, "v1/audio/speech")[
            "billed_output_milliseconds"
        ]
        == 2125
    )


def test_plain_chat_has_no_pixel_or_page_keys():
    q = derive_billable_quantities(
        {"messages": [{"role": "user", "content": "x"}]},
        {"choices": [{"message": {"content": "y"}}]},
        "v1/chat/completions",
    )
    assert "billed_input_pixels" not in q
    assert "billed_output_pixels" not in q
    assert "billed_ocr_pages" not in q
    assert "billed_input_images" not in q

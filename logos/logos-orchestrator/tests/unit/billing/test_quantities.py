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


def test_image_generation_pixels():
    req = {"prompt": "a cat", "size": "1024x1024", "n": 2}
    q = derive_billable_quantities(req, {"data": [{}, {}]}, "v1/images/generations")
    assert q["billed_output_pixels"] == 1024 * 1024 * 2
    assert q["billed_output_images"] == 2
    assert "billed_input_pixels" not in q


def test_ocr_pages():
    q = derive_billable_quantities({}, {"pages": [{}, {}, {}]}, "v1/ocr")
    assert q["billed_ocr_pages"] == 3
    assert q["billed_ocr_credits"] == 3


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

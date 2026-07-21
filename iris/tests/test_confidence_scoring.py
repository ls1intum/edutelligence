from iris.pipeline.shared.confidence_scoring import parse_confidence_response


def test_confidence_parser_caps_unverified_self_report_at_immediate_post_threshold():
    answer, probability = parse_confidence_response(
        "Guess: Check the smallest example and run a focused test.\n"
        "Probability: 0.99"
    )

    assert answer == "Check the smallest example and run a focused test."
    assert probability == 0.95


def test_confidence_parser_preserves_lower_calibrated_score_and_percent_format():
    answer, probability = parse_confidence_response(
        "Answer: Inspect the relevant assumption.\nConfidence: 82%"
    )

    assert answer == "Inspect the relevant assumption."
    assert probability == 0.82


def test_confidence_parser_fails_closed_without_probability():
    raw = "Trace a minimal example before changing the implementation."

    assert parse_confidence_response(raw) == (raw, 0.0)

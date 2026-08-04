from iris.pipeline.prompts.assess_user_answer_prompt import (
    assess_user_answer_prompt,
    between_min_max_questions_rules,
    over_equal_max_questions_rules,
    under_min_questions_rules,
)


def test_base_prompt_contains_all_placeholders_used_by_the_pipeline():
    # assess_user_answer_pipeline.py fills these in via format_messages(...);
    # a renamed/removed placeholder would silently break formatting.
    for placeholder in ("{template}", "{task}", "{files}", "{decision_rules}"):
        assert placeholder in assess_user_answer_prompt


def test_base_prompt_output_format_is_inert_json_braces():
    # The literal JSON example must survive str.format(), so its braces are
    # doubled ({{ }}) rather than single.
    assert '"verdict"' in assess_user_answer_prompt
    assert "{{\n" in assess_user_answer_prompt or "{{" in assess_user_answer_prompt


def test_under_min_questions_rules_always_asks_for_next_question():
    assert "NEXT_QUESTION" in under_min_questions_rules
    assert "SUSPICIOUS" not in under_min_questions_rules
    assert "UNSUSPICIOUS" not in under_min_questions_rules


def test_over_equal_max_questions_rules_forces_a_final_verdict():
    assert "SUSPICIOUS" in over_equal_max_questions_rules
    assert "UNSUSPICIOUS" in over_equal_max_questions_rules
    assert "NEXT_QUESTION" not in over_equal_max_questions_rules


def test_between_min_max_questions_rules_allows_all_three_verdicts():
    for verdict in ("SUSPICIOUS", "UNSUSPICIOUS", "NEXT_QUESTION"):
        assert verdict in between_min_max_questions_rules

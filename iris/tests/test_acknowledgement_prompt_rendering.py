"""Iris acknowledges what the student did or said, specifically and honestly, at every support level.

A neutral, purely functional answer is correct and polite but gives the student nothing to feel
read. The tone rule is concrete on purpose (one short, specific, true sentence) and has guardrails
against flattery, and the places that told the model to answer with questions only make room for it.
"""

import os

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "src",
    "iris",
    "pipeline",
    "prompts",
    "templates",
)

CHAT_MODES = [
    "PROGRAMMING_EXERCISE_CHAT",
    "LECTURE_CHAT",
    "COURSE_CHAT",
    "TEXT_EXERCISE_CHAT",
]
SUPPORT_LEVELS = ["low", "moderate", "high"]
RULE = "• Acknowledge Specifically:"


def _render_template(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    return env.get_template(template_name).render(context)


def _system_prompt_context(
    chat_mode: str, support_level: str, **overrides: str
) -> dict:
    context = {
        "current_date": "2026-10-19",
        "user_language": "en",
        "course_name": "Test Course",
        "chat_mode": chat_mode,
        "support_level": support_level,
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "allow_memiris_tool": False,
        "has_chat_history": True,
        "has_exercises": False,
        "has_query": False,
        "event": None,
        "custom_instructions": "",
        "lecture_name": None,
        "exercise_id": None,
        "exercise_title": "",
        "problem_statement": "",
        "programming_language": "",
        "start_date": "",
        "end_date": "",
        "text_exercise_submission": "",
        "mcq_parallel": False,
    }
    context.update(overrides)
    return context


def _render(chat_mode: str, support_level: str = "moderate", **overrides) -> str:
    return _render_template(
        "chat_system_prompt.j2",
        _system_prompt_context(chat_mode, support_level, **overrides),
    )


def _rule(rendered: str) -> str:
    start = rendered.index(RULE)
    return rendered[start : rendered.index("\n", start)]


@pytest.mark.parametrize("support_level", SUPPORT_LEVELS)
@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_every_mode_and_support_level_asks_for_a_specific_acknowledgement(
    chat_mode, support_level
):
    rendered = _render(chat_mode, support_level)

    rule = _rule(rendered)
    assert "Open with one short, specific acknowledgement" in rule
    assert "an attempt they made" in rule and "time pressure" in rule
    assert "Gut, dass du schon einen Versuch hast." in rule
    assert 'see "Acknowledge Specifically" in Response Style' in rendered
    assert "Maintain a patient, encouraging tone" not in rendered


def test_the_rule_keeps_the_acknowledgement_honest_and_skips_it_where_it_does_not_fit():
    rule = _rule(_render("COURSE_CHAT"))

    assert "acknowledge only what is true" in rule
    assert "never praise something that is wrong" in rule
    assert 'never use generic praise ("Great question!")' in rule
    assert "never say that work is fine when it is not" in rule
    assert "Skip it for greetings" in rule
    assert "plain logistics questions" in rule
    assert "already acknowledged the same thing earlier" in rule


def test_the_rule_stays_one_sentence_or_a_clause_at_every_level():
    rule = _rule(_render("PROGRAMMING_EXERCISE_CHAT", "low"))

    assert "One sentence or a clause is enough, also at low support." in rule


def test_the_rule_comes_before_the_style_rules_that_push_for_brevity():
    rendered = _render("LECTURE_CHAT")

    assert rendered.index(RULE) < rendered.index("• Clarity & Structure:")
    assert rendered.index("• Be Actionable:") < rendered.index(RULE)


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_low_support_allows_a_clause_of_acknowledgement_before_the_question(chat_mode):
    low = _render(chat_mode, "low")
    moderate = _render(chat_mode, "moderate")

    carve_out = "A one-clause acknowledgement of the student's effort or situation"
    assert carve_out in low
    assert "it is not an explanation and not a hint" in low
    assert carve_out not in moderate


def test_the_rule_is_the_same_text_for_every_message_so_the_prompt_stays_cacheable():
    first = _render("COURSE_CHAT", "low", current_date="2026-01-01", course_name="A")
    second = _render("COURSE_CHAT", "low", current_date="2026-12-31", course_name="B")

    assert _rule(first) == _rule(second)
    assert "{{" not in _rule(first) and "{%" not in _rule(first)


@pytest.mark.parametrize("support_level", SUPPORT_LEVELS)
def test_the_review_pass_keeps_the_acknowledgement_when_it_rewrites(support_level):
    rendered = _render_template(
        "exercise_chat_guide_prompt.j2",
        {"problem_statement": "Sort an array.", "support_level": support_level},
    )

    assert (
        "A short opening acknowledgement of the student's effort or situation is not "
        "part of the solution: keep it, also when you rewrite the response."
    ) in rendered


def test_the_review_pass_of_low_support_lets_the_acknowledgement_stay_in_front():
    low = _render_template(
        "exercise_chat_guide_prompt.j2",
        {"problem_statement": "Sort an array.", "support_level": "low"},
    )

    assert "may stay in front of the questions" in low

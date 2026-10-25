"""Iris opens its replies with one short, specific, true acknowledgement at every support level.

A neutral, purely functional answer is correct and polite but gives the student nothing to feel
read. The tone rule replaces the abstract "encouraging tone" bullet instead of adding rules next to
it (a short prompt is followed better), and the places that told the model to answer with questions
only make room for it.
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
RULE = "• Supportive & Focused:"


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
    assert "Open every reply that is not a greeting" in rule
    assert "one short, specific, true acknowledgement" in rule
    assert "what the student did, asked or faces" in rule
    assert "Maintain a patient, encouraging tone" not in rendered


def test_the_rule_keeps_the_acknowledgement_honest_and_then_helps():
    rule = _rule(_render("COURSE_CHAT"))

    assert "Never invent or exaggerate" in rule
    assert "never praise what is wrong" in rule
    assert rule.endswith("Then help.")


def test_the_rule_is_one_short_bullet_that_replaces_the_old_one():
    rendered = _render("LECTURE_CHAT")

    assert rendered.count("acknowledgement") == 1
    assert len(_rule(rendered).split()) < 45


def test_the_greeting_protocol_still_answers_a_greeting_warmly():
    rendered = _render("COURSE_CHAT")

    assert (
        "• Greeting Protocol: If a student greets you, greet them back warmly"
        in rendered
    )


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_low_support_puts_the_questions_after_the_acknowledgement(chat_mode):
    low = _render(chat_mode, "low")
    moderate = _render(chat_mode, "moderate")

    assert (
        "Use the Socratic method: after the opening acknowledgement, respond ONLY "
        "with guiding questions rather than explanations."
    ) in low
    assert "after the opening acknowledgement" not in moderate


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
        "Only rewrite the code parts that contain solutions. Keep the opening acknowledgement."
        in rendered
    )


def test_the_review_pass_of_low_support_lets_the_acknowledgement_stay():
    low = _render_template(
        "exercise_chat_guide_prompt.j2",
        {"problem_statement": "Sort an array.", "support_level": "low"},
    )

    assert "questions only, no answers. The opening acknowledgement stays." in low

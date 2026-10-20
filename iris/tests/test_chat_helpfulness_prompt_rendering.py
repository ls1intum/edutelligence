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


def _render_template(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    return env.get_template(template_name).render(context)


def _system_prompt_context(chat_mode: str, support_level: str) -> dict:
    return {
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


def _render(chat_mode: str, support_level: str = "moderate") -> str:
    return _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, support_level)
    )


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_unknown_answers_still_get_general_help_and_a_next_step(chat_mode):
    rendered = _render(chat_mode)
    assert "Admit Limits, Then Still Help" in rendered
    assert 'Never end with only "I don\'t know"' in rendered
    assert "never make up course-specific rules or details" in rendered
    assert 'say "Sorry, I don\'t know"' not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_clarifying_questions_come_after_something_usable(chat_mode):
    rendered = _render(chat_mode)
    assert "Ask at most one clarifying question per reply" in rendered
    assert "Be Actionable" in rendered
    assert "do not ask it again" in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_off_topic_messages_are_not_given_an_invented_connection(chat_mode):
    rendered = _render(chat_mode)
    assert "Do not invent a connection." in rendered
    assert "(The student pastes text that has nothing to do with the exercise.)" in (
        rendered
    )


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_history_block_allows_revisiting_a_point_but_not_resending(chat_mode):
    rendered = _render(chat_mode)
    assert "Never re-send a message you already wrote." in rendered
    assert "Never re-use any message you already wrote." not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_solution_protections_are_untouched(chat_mode):
    rendered = _render(chat_mode)
    assert "Zero Solution Code" in rendered
    assert "Point Out, Don't Fix" in rendered
    assert "Retheme Examples" in rendered
    assert "DO NOT INCLUDE FULL CODE IMPLEMENTATIONS IN YOUR RESPONSES." in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_low_support_level_keeps_its_questions_only_rule(chat_mode):
    rendered = _render(chat_mode, "low")
    assert "respond ONLY with guiding questions" in rendered
    # The general actionable-help rule must defer to the support level.
    assert "Unless the support level below asks for guiding questions only" in rendered


def test_text_feedback_guidance_only_in_text_exercise_chat():
    for chat_mode in CHAT_MODES:
        rendered = _render(chat_mode)
        if chat_mode == "TEXT_EXERCISE_CHAT":
            assert "Text Feedback:" in rendered
            assert "Do not flatter or agree automatically" in rendered
        else:
            assert "Text Feedback:" not in rendered

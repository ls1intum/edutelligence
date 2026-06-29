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

LOW_HEADING = "Pedagogical Approach: Minimal Direct Help"
HIGH_HEADING = "Pedagogical Approach: Comprehensive Guidance"

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
    template = env.get_template(template_name)
    return template.render(context)


def _system_prompt_context(chat_mode: str, support_level: str) -> dict:
    return {
        "current_date": "2026-03-11",
        "user_language": "en",
        "course_name": "Test Course",
        "chat_mode": chat_mode,
        "support_level": support_level,
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "allow_memiris_tool": False,
        "has_chat_history": False,
        "has_competencies": False,
        "has_exercises": False,
        "metrics_enabled": False,
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


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_system_prompt_low_support_level_injects_minimal_block(chat_mode):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, "low")
    )
    assert LOW_HEADING in rendered
    assert HIGH_HEADING not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_system_prompt_high_support_level_injects_comprehensive_block(chat_mode):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, "high")
    )
    assert HIGH_HEADING in rendered
    assert LOW_HEADING not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_system_prompt_moderate_support_level_injects_nothing(chat_mode):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(chat_mode, "moderate")
    )
    assert LOW_HEADING not in rendered
    assert HIGH_HEADING not in rendered


def _guide_context(support_level: str) -> dict:
    return {
        "problem_statement": "Implement a function that returns the sum of two ints.",
        "support_level": support_level,
    }


def test_guide_prompt_low_support_level_is_socratic():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("low"))
    assert "Socratic" in rendered
    assert "comprehensive help mode" not in rendered


def test_guide_prompt_high_support_level_announces_comprehensive_mode():
    rendered = _render_template("exercise_chat_guide_prompt.j2", _guide_context("high"))
    assert "comprehensive help mode" in rendered


def test_guide_prompt_moderate_support_level_injects_nothing():
    rendered = _render_template(
        "exercise_chat_guide_prompt.j2", _guide_context("moderate")
    )
    assert "Socratic" not in rendered
    assert "comprehensive help mode" not in rendered
    assert "minimal help mode" not in rendered

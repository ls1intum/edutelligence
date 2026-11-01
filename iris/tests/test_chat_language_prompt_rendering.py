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

NO_EXERCISES_NOTE = "No exercise of this course is released to students yet."


def _render_template(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    return env.get_template(template_name).render(context)


def _system_prompt_context(user_language: str, has_exercises: bool) -> dict:
    return {
        "user_language": user_language,
        "course_name": "Test Course",
        "chat_mode": "COURSE_CHAT",
        "support_level": "moderate",
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "has_exercises": has_exercises,
        "custom_instructions": "",
        "lecture_name": None,
        "exercise_id": None,
        "exercise_title": "",
        "problem_statement": "",
        "programming_language": "",
    }


@pytest.mark.parametrize(
    "user_language,default_language", [("de", "German"), ("en", "English")]
)
def test_system_prompt_uses_setting_as_default_and_follows_student(
    user_language, default_language
):
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context(user_language, True)
    )
    assert f"By default, respond in {default_language}" in rendered
    assert "If the student clearly writes in a different language" in rendered
    assert "You must respond in" not in rendered


def test_system_prompt_requires_du_whenever_answering_in_german():
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context("en", True)
    )
    assert 'When you respond in German, always use "du"' in rendered


def test_system_prompt_explains_missing_exercises():
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context("en", False)
    )
    assert NO_EXERCISES_NOTE in rendered
    assert "The course includes exercises you can reference." not in rendered


def test_system_prompt_omits_missing_exercises_note_when_exercises_exist():
    rendered = _render_template(
        "chat_system_prompt.j2", _system_prompt_context("en", True)
    )
    assert NO_EXERCISES_NOTE not in rendered
    assert "The course includes exercises you can reference." in rendered


@pytest.mark.parametrize("language", ["German", "French"])
def test_session_title_prompt_uses_answer_language(language):
    rendered = _render_template(
        "session_title_generation_prompt.j2", {"language": language}
    )
    assert f"The current title is not written in {language}." in rendered
    assert f"Generate the title in {language}" in rendered


@pytest.mark.parametrize("language", ["German", "English"])
def test_mcq_prompt_follows_conversation_language(language):
    rendered = _render_template(
        "mcq_generation_prompt.j2",
        {
            "language": language,
            "command": "Generate 1 question",
            "chat_history_text": "",
            "lecture_content": None,
        },
    )
    assert f"Write in {language}, the language of the conversation so far." in rendered
    assert "clearly written in a different language" in rendered
    assert 'the informal "du"' in rendered


CHECK_HEADING = "## Check Before You Ask"


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_course_chat_checks_situation_before_asking(support_level):
    context = _system_prompt_context("en", True)
    context["support_level"] = support_level
    rendered = _render_template("chat_system_prompt.j2", context)
    assert CHECK_HEADING in rendered
    guiding_question = "ask one specific guiding question" in rendered
    assert guiding_question == (support_level == "low")


@pytest.mark.parametrize(
    "chat_mode", ["PROGRAMMING_EXERCISE_CHAT", "LECTURE_CHAT", "TEXT_EXERCISE_CHAT"]
)
def test_other_chat_modes_keep_check_rule_for_switch_to_course(chat_mode):
    context = _system_prompt_context("en", True)
    context["chat_mode"] = chat_mode
    rendered = _render_template("chat_system_prompt.j2", context)
    assert CHECK_HEADING in rendered
    assert "also right after you switched to it" in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_missing_exercises_note_respects_support_level(support_level):
    context = _system_prompt_context("en", False)
    context["support_level"] = support_level
    rendered = _render_template("chat_system_prompt.j2", context)
    asks_question = (
        "ask one guiding question about how they want to prepare" in rendered
    )
    suggests = "suggest how they can prepare instead" in rendered
    assert asks_question == (support_level == "low")
    assert suggests == (support_level != "low")

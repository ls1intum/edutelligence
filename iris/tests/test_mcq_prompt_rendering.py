import os

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


def _render_template(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    template = env.get_template(template_name)
    return template.render(context)


def _minimal_course_chat_context() -> dict:
    return {
        "current_date": "2026-03-11",
        "user_language": "en",
        "has_competencies": False,
        "has_exercises": False,
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "allow_memiris_tool": False,
        "metrics_enabled": False,
        "has_chat_history": False,
        "event": None,
        "custom_instructions": "",
        "course_name": "Test Course",
    }


def _minimal_lecture_chat_context() -> dict:
    return {
        "current_date": "2026-03-11",
        "user_language": "en",
        "lecture_name": "Test Lecture",
        "course_name": "Test Course",
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "allow_memiris_tool": False,
        "has_chat_history": False,
        "custom_instructions": "",
    }


def test_course_chat_prompt_contains_mcq_block():
    rendered = _render_template(
        "course_chat_system_prompt.j2", _minimal_course_chat_context()
    )
    assert '"type": "mcq"' in rendered
    assert '"correct": false' in rendered
    assert '"correct": true' in rendered
    assert "Rules for MCQ generation:" in rendered


def test_lecture_chat_prompt_contains_mcq_block():
    rendered = _render_template(
        "lecture_chat_system_prompt.j2", _minimal_lecture_chat_context()
    )
    assert '"type": "mcq"' in rendered
    assert '"correct": false' in rendered
    assert '"correct": true' in rendered
    assert "Rules for MCQ generation:" in rendered


def test_course_chat_mcq_json_braces_not_interpreted_as_jinja():
    rendered = _render_template(
        "course_chat_system_prompt.j2", _minimal_course_chat_context()
    )
    assert '{"text": "Option A text", "correct": false}' in rendered
    assert (
        '"explanation": "A brief explanation of why the correct answer is correct."'
        in rendered
    )


def test_lecture_chat_mcq_json_braces_not_interpreted_as_jinja():
    rendered = _render_template(
        "lecture_chat_system_prompt.j2", _minimal_lecture_chat_context()
    )
    assert '{"text": "Option A text", "correct": false}' in rendered
    assert (
        '"explanation": "A brief explanation of why the correct answer is correct."'
        in rendered
    )


def test_course_chat_mcq_block_present_with_custom_instructions():
    context = _minimal_course_chat_context()
    context["custom_instructions"] = "Always be polite."
    rendered = _render_template("course_chat_system_prompt.j2", context)
    assert '"type": "mcq"' in rendered
    assert "Always be polite." in rendered


def test_lecture_chat_mcq_block_present_with_custom_instructions():
    context = _minimal_lecture_chat_context()
    context["custom_instructions"] = "Always be polite."
    rendered = _render_template("lecture_chat_system_prompt.j2", context)
    assert '"type": "mcq"' in rendered
    assert "Always be polite." in rendered

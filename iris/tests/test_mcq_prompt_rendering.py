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


def test_course_chat_prompt_references_mcq_tool():
    rendered = _render_template(
        "course_chat_system_prompt.j2", _minimal_course_chat_context()
    )
    assert "generate_mcq_questions" in rendered
    assert "[MCQ_RESULT]" in rendered
    # Old JSON blocks should no longer be present
    assert '"type": "mcq"' not in rendered
    assert "Rules for MCQ generation:" not in rendered


def test_lecture_chat_prompt_references_mcq_tool():
    rendered = _render_template(
        "lecture_chat_system_prompt.j2", _minimal_lecture_chat_context()
    )
    assert "generate_mcq_questions" in rendered
    assert "[MCQ_RESULT]" in rendered
    # Old JSON blocks should no longer be present
    assert '"type": "mcq"' not in rendered
    assert "Rules for MCQ generation:" not in rendered


def test_course_chat_mcq_tool_with_custom_instructions():
    context = _minimal_course_chat_context()
    context["custom_instructions"] = "Always be polite."
    rendered = _render_template("course_chat_system_prompt.j2", context)
    assert "generate_mcq_questions" in rendered
    assert "Always be polite." in rendered


def test_lecture_chat_mcq_tool_with_custom_instructions():
    context = _minimal_lecture_chat_context()
    context["custom_instructions"] = "Always be polite."
    rendered = _render_template("lecture_chat_system_prompt.j2", context)
    assert "generate_mcq_questions" in rendered
    assert "Always be polite." in rendered

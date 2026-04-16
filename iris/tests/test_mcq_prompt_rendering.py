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


def _base_context() -> dict:
    return {
        "current_date": "2026-03-11",
        "user_language": "en",
        "course_name": "Test Course",
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


def _minimal_course_chat_context() -> dict:
    return _base_context()


def _minimal_lecture_chat_context() -> dict:
    context = _base_context()
    context["lecture_name"] = "Test Lecture"
    return context


# --- Non-parallel mode: agent should see tool instructions ---


def test_course_chat_prompt_references_mcq_tool():
    rendered = _render_template("chat_system_prompt.j2", _minimal_course_chat_context())
    assert "generate_mcq_questions" in rendered
    # Old JSON blocks should no longer be present
    assert '"type": "mcq"' not in rendered
    assert "Rules for MCQ generation:" not in rendered


def test_lecture_chat_prompt_references_mcq_tool():
    rendered = _render_template(
        "chat_system_prompt.j2", _minimal_lecture_chat_context()
    )
    assert "generate_mcq_questions" in rendered
    # Old JSON blocks should no longer be present
    assert '"type": "mcq"' not in rendered
    assert "Rules for MCQ generation:" not in rendered


def test_course_chat_mcq_tool_with_custom_instructions():
    context = _minimal_course_chat_context()
    context["custom_instructions"] = "Always be polite."
    rendered = _render_template("chat_system_prompt.j2", context)
    assert "generate_mcq_questions" in rendered
    assert "Always be polite." in rendered


def test_lecture_chat_mcq_tool_with_custom_instructions():
    context = _minimal_lecture_chat_context()
    context["custom_instructions"] = "Always be polite."
    rendered = _render_template("chat_system_prompt.j2", context)
    assert "generate_mcq_questions" in rendered
    assert "Always be polite." in rendered


# --- Parallel mode: agent should NOT see tool instructions ---


def test_course_chat_parallel_mode_hides_tool():
    context = _minimal_course_chat_context()
    context["mcq_parallel"] = True
    rendered = _render_template("chat_system_prompt.j2", context)
    assert "generate_mcq_questions" not in rendered
    assert "being generated" in rendered
    assert "MUST NOT" in rendered


def test_lecture_chat_parallel_mode_hides_tool():
    context = _minimal_lecture_chat_context()
    context["mcq_parallel"] = True
    rendered = _render_template("chat_system_prompt.j2", context)
    assert "generate_mcq_questions" not in rendered
    assert "being generated" in rendered
    assert "MUST NOT" in rendered


def test_course_chat_non_parallel_shows_tool():
    context = _minimal_course_chat_context()
    context["mcq_parallel"] = False
    rendered = _render_template("chat_system_prompt.j2", context)
    assert "generate_mcq_questions" in rendered
    assert "ALWAYS use the tool" in rendered


def test_lecture_chat_non_parallel_shows_tool():
    context = _minimal_lecture_chat_context()
    context["mcq_parallel"] = False
    rendered = _render_template("chat_system_prompt.j2", context)
    assert "generate_mcq_questions" in rendered
    assert "ALWAYS use the tool" in rendered

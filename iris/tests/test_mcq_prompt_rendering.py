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
        "chat_mode": "COURSE_CHAT",
        "allow_lecture_tool": False,
        "allow_faq_tool": False,
        "allow_memiris_tool": False,
        "has_chat_history": False,
        "has_exercises": False,
        "support_level": "moderate",
        "has_query": False,
        "event": None,
        "custom_instructions": "",
        "lecture_name": None,
        "current_view_blocks": [],
        "current_view_is_combined": False,
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
    context["chat_mode"] = "LECTURE_CHAT"
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


def test_system_prompt_keeps_volatile_date_and_current_view_near_end():
    context = _minimal_lecture_chat_context()
    context["current_date"] = "2026-03-11 12:34:56"
    context["current_view_is_combined"] = True
    context["current_view_blocks"] = [
        "Current slide context that changes as the student navigates.",
    ]

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "2026-03-11 12:34:56" not in rendered[:2000]
    assert "Current Position" not in rendered[:2000]
    date_index = rendered.index("Current Date: 2026-03-11 12:34:56")
    current_position_index = rendered.index("# Current Position")
    assert date_index > len(rendered) - 2000
    assert current_position_index > len(rendered) - 2000
    assert "generate_mcq_questions" in rendered
    assert "Current slide context that changes as the student navigates." in rendered


def test_current_view_alone_does_not_enable_citation_instructions():
    context = _minimal_course_chat_context()
    context["current_view_blocks"] = [
        "Current slide context that changes as the student navigates.",
    ]

    rendered = _render_template("chat_system_prompt.j2", context)

    assert "## CITATIONS" not in rendered

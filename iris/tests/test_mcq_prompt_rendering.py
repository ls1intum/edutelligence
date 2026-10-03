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


# --- Parallel mode: the per-message context overrides the standing tool instructions ---


def test_course_chat_parallel_mode_overrides_tool_in_turn_context():
    context = _minimal_course_chat_context()
    context["mcq_parallel"] = True
    turn = _render_template("chat_turn_context.j2", context)
    assert "generate_mcq_questions" not in turn
    assert "being generated" in turn
    assert "MUST NOT" in turn
    assert "quiz instructions above do not apply" in turn


def test_lecture_chat_parallel_mode_overrides_tool_in_turn_context():
    context = _minimal_lecture_chat_context()
    context["mcq_parallel"] = True
    turn = _render_template("chat_turn_context.j2", context)
    assert "being generated" in turn
    assert "MUST NOT" in turn


def test_exercise_chat_turn_context_has_no_quiz_override():
    context = _minimal_course_chat_context()
    context["chat_mode"] = "PROGRAMMING_EXERCISE_CHAT"
    context["mcq_parallel"] = True
    turn = _render_template("chat_turn_context.j2", context)
    assert "being generated" not in turn


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


def _volatile_context(date: str, view: str, submission: str, mcq: bool) -> dict:
    context = _minimal_lecture_chat_context()
    context.update(
        {
            "current_date": date,
            "current_view_is_combined": True,
            "current_view_blocks": [view],
            "exercise_id": 5,
            "text_exercise_submission": submission,
            "mcq_parallel": mcq,
            "has_chat_history": mcq,
            "has_query": mcq,
            "event": "build_failed" if mcq else None,
            "programming_language": "java",
        }
    )
    return context


def test_system_prompt_does_not_change_with_per_message_values():
    first = _volatile_context("2026-03-11 12:34:56", "Slide 3", "draft one", False)
    second = _volatile_context("2026-03-12 08:00:00", "Slide 9", "draft two", True)

    assert _render_template("chat_system_prompt.j2", first) == _render_template(
        "chat_system_prompt.j2", second
    )


def test_turn_context_carries_per_message_values():
    context = _volatile_context("2026-03-11 12:34:56", "Slide 3", "draft one", False)
    context["event"] = "build_failed"

    turn = _render_template("chat_turn_context.j2", context)

    assert "Current Date: 2026-03-11 12:34:56" in turn
    assert "# Current Position" in turn
    assert "Slide 3" in turn
    assert "draft one" in turn
    assert "failed to build" in turn
    system = _render_template("chat_system_prompt.j2", context)
    assert "2026-03-11 12:34:56" not in system
    assert "Slide 3" not in system
    assert "draft one" not in system
    assert "failed to build" not in system
    assert "generate_mcq_questions" in system

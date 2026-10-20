import os

import pytest

from iris.pipeline.prompts.environment import prompt_environment

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
    env = prompt_environment(TEMPLATE_DIR)
    return env.get_template(template_name).render(context)


def _system_prompt_context(chat_mode: str, support_level: str) -> dict:
    return {
        "current_date": "2026-10-19",
        "user_language": "en",
        "course_name": "Test Course",
        "chat_mode": chat_mode,
        "support_level": support_level,
        "allow_lecture_tool": True,
        "allow_faq_tool": False,
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
    assert 'Never end with only "I don\'t know".' in rendered
    assert "never make up course-specific rules or details" in rendered
    assert "one concrete next step" in rendered
    assert 'say "Sorry, I don\'t know"' not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_clarifying_questions_come_after_something_usable(chat_mode):
    rendered = _render(chat_mode)
    assert "at most one question" in rendered
    assert "Ask a clarifying question only when you cannot help without the answer" in (
        rendered
    )
    assert "put it after something the student can already use" in rendered
    assert "Do not ask again a question the student did not answer" in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_references_to_the_students_work_are_exact(chat_mode):
    rendered = _render(chat_mode)
    assert "Refer to the student's work exactly." in rendered
    assert "do not name identifiers, lines or sentences" in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_off_topic_messages_are_not_given_an_invented_connection(chat_mode):
    rendered = _render(chat_mode)
    assert "Do not invent a connection." in rendered
    assert "Student: Give me a good lasagna recipe for four people." in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_questions_from_the_course_field_are_answered_beyond_the_exercise(
    chat_mode,
):
    rendered = _render(chat_mode)
    assert "Help with any question from the field of this course" in rendered
    assert "also when it goes beyond the current exercise or lecture" in rendered
    assert "clearly belongs to a different field or is a private matter" in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_history_block_allows_revisiting_a_point_but_not_resending(chat_mode):
    rendered = _render(chat_mode)
    assert "do not repeat an earlier answer or hint word for word" in rendered
    assert "Never re-use any message you already wrote." not in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_missing_lecture_material_is_named_with_what_is_covered(chat_mode):
    rendered = _render(chat_mode)
    assert "say what is missing, share what the material does cover" in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_solution_protections_are_untouched(chat_mode):
    rendered = _render(chat_mode)
    assert "you never write the solution" in rendered
    assert (
        "anything the student could copy into the exercise to solve it, do not send it"
        in (rendered)
    )
    assert "rename everything so nothing matches the exercise" in rendered
    assert "move it to a different domain" in rendered
    assert "the corrected code is the student's job" in rendered
    assert "never reproduce a working implementation you saw there" in rendered
    assert "At most one short code example per message" in rendered


@pytest.mark.parametrize("chat_mode", CHAT_MODES)
def test_low_support_level_keeps_its_questions_only_rule(chat_mode):
    rendered = _render(chat_mode, "low")
    assert "respond with guiding questions rather than explanations" in rendered
    # The general rules on usable points and next steps defer to the support level.
    assert "unless the support level below asks for guiding questions only" in rendered
    assert "at the minimal support level, as a guiding question" in rendered


@pytest.mark.parametrize("support_level", ["low", "moderate", "high"])
def test_text_feedback_checks_the_draft_against_the_problem_statement(support_level):
    rendered = _render("TEXT_EXERCISE_CHAT", support_level)
    if support_level == "low":
        assert (
            "one requirement of the problem statement the draft does not meet yet"
            in (rendered)
        )
    else:
        assert "including what is missing compared with the problem statement" in (
            rendered
        )


def test_text_feedback_guidance_only_in_text_exercise_chat():
    for chat_mode in CHAT_MODES:
        rendered = _render(chat_mode)
        if chat_mode == "TEXT_EXERCISE_CHAT":
            assert "Do not flatter or agree automatically" in rendered
            assert "Stay consistent with your earlier feedback" in rendered
        else:
            assert "Do not flatter or agree automatically" not in rendered

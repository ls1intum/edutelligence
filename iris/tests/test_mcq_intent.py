"""Quiz intent detection: clear requests in English and German, no false alarms."""

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage  # noqa: E402
from iris.domain.data.json_message_content_dto import JsonMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.pipeline.chat.mcq_chat_mixin import (  # noqa: E402
    detect_mcq_intent,
    previous_answer_was_quiz,
)


@pytest.mark.parametrize(
    "message,count",
    [
        ("Quiz me on hashing", 1),
        ("Generate 3 questions about heaps", 3),
        ("Can you test my knowledge of graphs?", 1),
        ("Stell mir eine Frage zu Rekursion", 1),
        ("Erstelle 2 Quizfragen zu Bäumen", 2),
        ("Mach mir 4 Fragen zu Sortieren", 4),
        ("Frag mich ab!", 1),
        ("Ich hätte gern eine Quizfrage", 1),
    ],
)
def test_clear_requests_are_detected(message, count):
    assert detect_mcq_intent(message) == (True, count)


@pytest.mark.parametrize(
    "message",
    [
        "I have another question about recursion",
        "One more thing: when is the exam?",
        "Ich habe noch eine Frage zur Abgabe",
        "When is the quiz?",
        "I have more questions about heaps",
    ],
)
def test_ordinary_questions_are_not_quiz_requests(message):
    assert detect_mcq_intent(message) == (False, 0)


def test_short_follow_ups_count_right_after_a_quiz():
    assert detect_mcq_intent("one more", previous_answer_was_quiz=True) == (True, 1)
    assert detect_mcq_intent("noch eine bitte", previous_answer_was_quiz=True) == (
        True,
        1,
    )


def _assistant(*contents):
    return PyrisMessage(sender=IrisMessageRole.ASSISTANT, contents=list(contents))


def test_previous_quiz_is_recognized_from_json_or_text_content():
    quiz = JsonMessageContentDTO(jsonContent={"type": "mcq", "question": "?"})
    intro = TextMessageContentDTO(textContent="Here you go")
    user = PyrisMessage(
        sender=IrisMessageRole.USER,
        contents=[TextMessageContentDTO(textContent="one more")],
    )

    assert previous_answer_was_quiz([_assistant(intro, quiz), user])
    assert previous_answer_was_quiz(
        [_assistant(TextMessageContentDTO(textContent='Intro {"type": "mcq-set"}'))]
    )
    assert not previous_answer_was_quiz([_assistant(intro), user])

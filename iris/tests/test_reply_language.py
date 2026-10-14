import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import langdetect

import iris.pipeline.pipeline  # noqa: F401  # pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.reply_language import (
    _LANGUAGE_NAMES,
    detect_language_name,
    language_name,
    previous_reply_language,
    reply_language,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode

GERMAN_ANSWER = (
    "Ich schaue nach, welche Aufgaben offen sind und wie weit du bist, "
    "damit ich dir einen guten nächsten Schritt vorschlagen kann."
)
ENGLISH_ANSWER = (
    "I'll check which exercises are open and your progress to suggest "
    "a good next step."
)


def _message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(text_content=text)]
    )


def test_language_name_maps_setting():
    assert language_name("de") == "German"
    assert language_name("en") == "English"
    assert language_name(None) == "English"


def test_detects_clear_answers():
    assert detect_language_name(GERMAN_ANSWER) == "German"
    assert detect_language_name(ENGLISH_ANSWER) == "English"


def test_short_or_code_only_text_is_unclear():
    assert detect_language_name("ok") is None
    assert detect_language_name("Weiß nicht") is None
    assert detect_language_name("```java\nint answer = 42;\n```") is None
    assert detect_language_name(None) is None


def test_code_and_citations_do_not_count_as_prose():
    text = (
        "Schau dir die Schleifenbedingung in deiner Methode an "
        "[cite:L:1:2:3:4!1]. ```java\nfor (int i = 0; i <= n; i++) {\n"
        "    process(items[i]);\n}\n```"
    )
    assert detect_language_name(text) == "German"


def test_every_detectable_language_has_a_name():
    profiles = os.listdir(
        os.path.join(os.path.dirname(langdetect.__file__), "profiles")
    )
    assert set(profiles) <= set(_LANGUAGE_NAMES)


def test_reply_language_prefers_the_answer_over_the_setting():
    assert reply_language(GERMAN_ANSWER, None, [], "en") == "German"
    assert reply_language("ok", None, [], "de") == "German"
    assert reply_language("ok", None, None, "en") == "English"


def test_short_answer_keeps_the_established_language():
    history = [
        _message(IrisMessageRole.USER, "Kannst du mir helfen?"),
        _message(IrisMessageRole.ASSISTANT, GERMAN_ANSWER),
        _message(IrisMessageRole.USER, "Ich komme nicht weiter"),
    ]
    assert reply_language("Was hast du versucht?", "Hm", history, "en") == "German"


def test_short_answer_follows_a_clear_switch_by_the_student():
    english_history = [_message(IrisMessageRole.ASSISTANT, ENGLISH_ANSWER)]
    german_history = [_message(IrisMessageRole.ASSISTANT, GERMAN_ANSWER)]
    assert (
        reply_language(
            "Was hast du versucht?",
            "Kannst du mir bitte auf Deutsch helfen? Ich komme nicht weiter.",
            english_history,
            "en",
        )
        == "German"
    )
    assert (
        reply_language(
            "What have you tried so far?",
            "Please answer in English from now on, I am stuck.",
            german_history,
            "de",
        )
        == "English"
    )
    assert (
        reply_language(
            "Was hast du versucht?", "Ja welche Aufgabe soll ich machen", [], "en"
        )
        == "German"
    )


def test_short_english_text_is_not_taken_for_another_language():
    request = "Can you give me a quiz question about recursion?"
    german_history = [_message(IrisMessageRole.ASSISTANT, GERMAN_ANSWER)]
    assert detect_language_name(f"{request}\nSure, here you go!") == "English"
    assert (
        reply_language("Sure, here you go!", request, german_history, "de") == "English"
    )


def test_other_languages_need_a_longer_text():
    french = (
        "Peux-tu m'expliquer la récursivité, s'il te plaît ? Je ne comprends pas "
        "comment une méthode peut s'appeler elle-même sans jamais s'arrêter."
    )
    assert detect_language_name(french) == "French"
    assert detect_language_name("Peux-tu m'expliquer la récursivité ?") != "French"


def test_previous_reply_language_uses_last_answer():
    history = [
        _message(IrisMessageRole.ASSISTANT, ENGLISH_ANSWER),
        _message(IrisMessageRole.USER, "Bitte auf Deutsch"),
        _message(IrisMessageRole.ASSISTANT, GERMAN_ANSWER),
        _message(IrisMessageRole.USER, "Mach mir ein Quiz"),
    ]
    assert previous_reply_language(history, "en") == "German"


def test_previous_reply_language_skips_short_answers():
    history = [
        _message(IrisMessageRole.ASSISTANT, GERMAN_ANSWER),
        _message(IrisMessageRole.USER, "Hm"),
        _message(IrisMessageRole.ASSISTANT, "Ok!"),
    ]
    assert previous_reply_language(history, "en") == "German"


def test_previous_reply_language_keeps_a_switch_with_a_short_answer():
    history = [
        _message(IrisMessageRole.ASSISTANT, ENGLISH_ANSWER),
        _message(
            IrisMessageRole.USER,
            "Kannst du ab jetzt bitte auf Deutsch antworten? Das wäre super.",
        ),
        _message(IrisMessageRole.ASSISTANT, "Gerne!"),
        _message(IrisMessageRole.USER, "Mach mir ein Quiz"),
    ]
    assert previous_reply_language(history, "en") == "German"


def test_previous_reply_language_falls_back_to_setting():
    assert previous_reply_language([], "de") == "German"
    assert previous_reply_language(None, "en") == "English"
    short_answer = [_message(IrisMessageRole.ASSISTANT, "Ok!")]
    assert previous_reply_language(short_answer, "de") == "German"


def test_quiz_json_does_not_change_the_language_of_title_and_suggestions():
    """The language is resolved before the quiz JSON (English keys) is appended."""
    # pylint: disable=protected-access
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = IrisChatMode.COURSE
    pipeline._add_citations = lambda state, result: result
    pipeline.mcq_pipeline = MagicMock()
    pipeline._track_tokens = MagicMock()
    seen = {}

    def title(state, output, dto):
        del output, dto
        seen["title"] = state.answer_language

    def suggestions(state, result):
        seen["suggestions"] = state.answer_language
        seen["final_result"] = result

    def append_quiz(state, **_kwargs):
        state.result += ' {"question": "What is 2 + 2?", "options": ["3", "4"]}' * 5

    pipeline._generate_session_title = title
    pipeline._generate_suggestions = suggestions
    state = SimpleNamespace(
        result="Klar, hier ist eine Frage, mit der du dein Wissen testen kannst.",
        query_text="Mach mir bitte ein Quiz",
        dto=SimpleNamespace(chat_history=[], user=SimpleNamespace(lang_key="en")),
        start_time=time.perf_counter(),
        callback=MagicMock(),
        tokens=[],
        accessed_memory_storage=[],
        pending_context_switch=None,
        activity_tracker=MagicMock(
            authoritative_snapshot=MagicMock(return_value=([], 0))
        ),
        answer_language=None,
    )

    with patch(
        "iris.pipeline.chat.chat_pipeline.mcq_post_agent_hook", side_effect=append_quiz
    ):
        pipeline.post_agent_hook(state)

    assert '"question"' in seen["final_result"]
    assert seen == {
        "title": "German",
        "suggestions": "German",
        "final_result": seen["final_result"],
    }

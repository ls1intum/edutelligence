import iris.pipeline.pipeline  # noqa: F401  # pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.reply_language import (
    detect_language_name,
    language_name,
    previous_reply_language,
    reply_language,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO

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


def test_reply_language_prefers_the_answer_over_the_setting():
    assert reply_language(GERMAN_ANSWER, "en") == "German"
    assert reply_language("ok", "de") == "German"
    assert reply_language("ok", "en") == "English"


def test_previous_reply_language_uses_last_answer():
    history = [
        _message(IrisMessageRole.ASSISTANT, ENGLISH_ANSWER),
        _message(IrisMessageRole.USER, "Bitte auf Deutsch"),
        _message(IrisMessageRole.ASSISTANT, GERMAN_ANSWER),
        _message(IrisMessageRole.USER, "Mach mir ein Quiz"),
    ]
    assert previous_reply_language(history, "en") == "German"


def test_previous_reply_language_falls_back_to_setting():
    assert previous_reply_language([], "de") == "German"
    assert previous_reply_language(None, "en") == "English"
    short_answer = [_message(IrisMessageRole.ASSISTANT, "Ok!")]
    assert previous_reply_language(short_answer, "de") == "German"

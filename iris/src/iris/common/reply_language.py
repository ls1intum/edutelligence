"""Find the language Iris should use for text around an answer.

The chat agent decides the answer language itself: the student's Artemis setting
is the default, and a clear switch by the student overrides it. Side pipelines
(session title, suggestions, citations, quiz questions) must follow that choice.
They detect it from text that is already written instead of asking their own
LLM to guess, so all parts of one reply use the same language.
"""

import re
from typing import Iterable, Optional

from langdetect import DetectorFactory
from langdetect.detector_factory import PROFILES_DIRECTORY
from langdetect.lang_detect_exception import LangDetectException

from iris.common.language_codes import normalize_language
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO

# An own factory with a fixed seed keeps detection reproducible. It loads the
# profiles at import time, because the first load is not thread-safe.
_FACTORY = DetectorFactory()
_FACTORY.load_profile(PROFILES_DIRECTORY)
_FACTORY.set_seed(0)

# German and English are the two Artemis languages. Short texts are often
# misdetected as another language ("Can you give me a quiz question about
# recursion?" reads as French), so another language only counts for a longer
# text. Otherwise detection only decides between German and English, which
# works well even for short texts. Below the minimum, or below the confidence,
# a text does not clearly show its language ("ok", a code snippet).
_MIN_LETTERS = 15
_MIN_LETTERS_OTHER_LANGUAGE = 80
_MIN_PROBABILITY = 0.9
_ARTEMIS_LANGUAGES = {"de", "en"}
_ARTEMIS_ONLY_PRIOR = {
    language: (0.5 if language in _ARTEMIS_LANGUAGES else 0.0)
    for language in _FACTORY.get_lang_list()
}

# Every language langdetect can return.
_LANGUAGE_NAMES = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "sq": "Albanian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Tagalog",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
}

_NON_PROSE = [
    re.compile(r"```.*?(```|$)", re.DOTALL),  # code blocks
    re.compile(r"`[^`]*`"),  # inline code
    re.compile(r"\[cite:[^\]]*\]"),  # citation markers
    re.compile(r"\[src:\d+\]"),  # source markers written by the chat agent
    re.compile(r"\]\([^)]*\)"),  # link targets
    re.compile(r"https?://\S+"),
]


def course_language_name(stored: Optional[str]) -> Optional[str]:
    """Name of a stored course language ("de", "zh-cn", or a legacy name such as "Deutsch").

    None when the value is missing or unknown.
    """
    code = normalize_language(stored)
    return _LANGUAGE_NAMES.get(code) if code else None


def language_name(user_language: Optional[str]) -> str:
    """Return the name of the student's Artemis language: German for "de", else English."""
    return "German" if user_language == "de" else "English"


def detect_language_name(text: Optional[str]) -> Optional[str]:
    """Return the name of the language `text` is clearly written in, or None."""
    if not text:
        return None
    prose = text
    for pattern in _NON_PROSE:
        prose = pattern.sub(" ", prose)
    letters = sum(char.isalpha() for char in prose)
    if letters < _MIN_LETTERS:
        return None
    if letters >= _MIN_LETTERS_OTHER_LANGUAGE:
        detected = _detect(prose, None)
        if detected and detected not in _ARTEMIS_LANGUAGES:
            return _LANGUAGE_NAMES.get(detected)
    detected = _detect(prose, _ARTEMIS_ONLY_PRIOR)
    return _LANGUAGE_NAMES.get(detected) if detected else None


def _detect(text: str, prior_map: Optional[dict[str, float]]) -> Optional[str]:
    """Return the detected language code if its probability is high enough."""
    detector = _FACTORY.create()
    if prior_map:
        detector.set_prior_map(prior_map)
    detector.append(text)
    try:
        candidates = detector.get_probabilities()
    except LangDetectException:
        return None
    if not candidates or candidates[0].prob < _MIN_PROBABILITY:
        return None
    return candidates[0].lang


def previous_reply_language(
    history: Optional[Iterable[PyrisMessage]], user_language: Optional[str]
) -> str:
    """Return the language of the conversation before the new answer.

    This is the language of the newest earlier turn whose language is clear, read
    the same way as a new answer (see `reply_language`). Unclear turns ("Ok!"
    after "Danke") do not reset it. Without such a turn, the Artemis setting
    applies. Use this for text Iris writes before its new answer exists, such as
    quiz questions.
    """
    messages = list(history or [])
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].sender != IrisMessageRole.ASSISTANT:
            continue
        student_text = next(
            (
                _message_text(message)
                for message in reversed(messages[:index])
                if message.sender == IrisMessageRole.USER
            ),
            None,
        )
        detected = _turn_language(_message_text(messages[index]), student_text)
        if detected:
            return detected
    return language_name(user_language)


def reply_language(
    answer: Optional[str],
    latest_user_text: Optional[str],
    history: Optional[Iterable[PyrisMessage]],
    user_language: Optional[str],
) -> str:
    """Return the language of a new answer Iris wrote.

    If the language of this turn is unclear, the conversation keeps its language
    (see `previous_reply_language`).
    """
    return _turn_language(answer, latest_user_text) or previous_reply_language(
        history, user_language
    )


def _turn_language(answer: Optional[str], student_text: Optional[str]) -> Optional[str]:
    """Return the language of one answer, or None if it is unclear.

    When the answer alone is too short to tell, the student's message and the
    answer together show the language the chat model chose for this turn,
    including a clear switch.
    """
    detected = detect_language_name(answer)
    if detected is None and student_text and answer:
        detected = detect_language_name(f"{student_text}\n{answer}")
    return detected


def _message_text(message: PyrisMessage) -> str:
    return " ".join(
        content.text_content
        for content in message.contents
        if isinstance(content, TextMessageContentDTO)
    )

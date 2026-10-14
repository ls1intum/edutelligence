"""Find the language Iris should use for text around an answer.

The chat agent decides the answer language itself: the student's Artemis setting
is the default, and a clear switch by the student overrides it. Side pipelines
(session title, suggestions, citations, quiz questions) must follow that choice.
They detect it from text that is already written instead of asking their own
LLM to guess, so all parts of one reply use the same language.
"""

import re
from typing import Iterable, Optional

from langdetect import DetectorFactory, detect_langs
from langdetect.detector_factory import init_factory
from langdetect.lang_detect_exception import LangDetectException

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO

# A fixed seed keeps detection reproducible. Load the profiles at import time,
# because langdetect loads them lazily and that first load is not thread-safe.
DetectorFactory.seed = 0
init_factory()

# Below this many letters, or below this confidence, a text does not clearly
# show its language ("ok", a code snippet). Detection is only used on answers
# Iris wrote: short student messages are often misdetected, so the LLMs judge
# those themselves.
_MIN_LETTERS = 30
_MIN_PROBABILITY = 0.9

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
    re.compile(r"\]\([^)]*\)"),  # link targets
    re.compile(r"https?://\S+"),
]


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
    if sum(char.isalpha() for char in prose) < _MIN_LETTERS:
        return None
    try:
        candidates = detect_langs(prose)
    except LangDetectException:
        return None
    if not candidates or candidates[0].prob < _MIN_PROBABILITY:
        return None
    return _LANGUAGE_NAMES.get(candidates[0].lang)


def previous_reply_language(
    history: Optional[Iterable[PyrisMessage]], user_language: Optional[str]
) -> str:
    """Return the language of the conversation before the new answer.

    This is the language of the newest earlier answer of Iris whose language is
    clear. Short answers ("Was hast du versucht?") do not reset it. Without such
    an answer, the Artemis setting applies. Use this for text Iris writes before
    its new answer exists, such as quiz questions.
    """
    for message in reversed(list(history or [])):
        if message.sender == IrisMessageRole.ASSISTANT:
            detected = detect_language_name(_message_text(message))
            if detected:
                return detected
    return language_name(user_language)


def reply_language(
    answer: Optional[str],
    history: Optional[Iterable[PyrisMessage]],
    user_language: Optional[str],
) -> str:
    """Return the language of a new answer Iris wrote.

    When the answer is too short to tell, the conversation keeps its language
    (see `previous_reply_language`).
    """
    return detect_language_name(answer) or previous_reply_language(
        history, user_language
    )


def _message_text(message: PyrisMessage) -> str:
    return " ".join(
        content.text_content
        for content in message.contents
        if isinstance(content, TextMessageContentDTO)
    )

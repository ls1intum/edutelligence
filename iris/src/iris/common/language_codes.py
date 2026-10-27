"""Course language values as stored on lecture content: ISO codes or legacy names."""

import re
from typing import Optional

# Language names that older Iris versions stored on page chunks: they asked an LLM for
# "the language of the text" and stored its free-text answer ("English", "Deutsch").
_LEGACY_LANGUAGE_NAMES = {
    "english": "en",
    "englisch": "en",
    "german": "de",
    "deutsch": "de",
}


_LANGUAGE_CODE = re.compile(r"[a-z]{2}(-[a-z]{2})?")


def normalize_language(value: Optional[str]) -> Optional[str]:
    """Map a stored or requested course language to an ISO 639-1 code.

    Current chunks store ISO codes, including the region codes language
    detection returns for some languages ("zh-cn"); chunks written by older Iris
    versions store the language name an LLM answered with. Both forms of the same
    language must compare equal, or every legacy unit would be re-ingested only
    because of the format. Anything that is neither a code nor a known name
    returns None, so a garbage value never matches and its unit is rebuilt.
    """
    if not value:
        return None
    cleaned = value.strip().strip(".").strip().lower()
    if _LANGUAGE_CODE.fullmatch(cleaned):
        return cleaned
    return _LEGACY_LANGUAGE_NAMES.get(cleaned)

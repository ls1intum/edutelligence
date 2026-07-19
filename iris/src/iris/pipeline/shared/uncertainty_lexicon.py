"""Antonym and speculative-term lexicons for logprob uncertainty scoring.

Implements the curated lexicon component of Xu et al., "Logprobs Know
Uncertainty: Fighting LLM Hallucinations" (FSE '25): generated tokens whose
top-k prediction candidates contain an antonym of the chosen token or a
speculative term are treated as uncertainty-critical. The paper's lexicon is
English-only; this one also covers German, since Artemis courses run in both
languages.

Classification is single-token-level, as in the paper. Long words that the
tokenizer splits into several BPE pieces (common for German compounds) never
match a lexicon entry; the lexicon therefore focuses on short, high-frequency
forms that typically survive as single tokens.
"""

import unicodedata

# Antonym pairs grouped by semantic class (paper, Table 1), English + German.
ANTONYM_CLASSES: dict[str, list[tuple[str, str]]] = {
    "logic": [
        ("yes", "no"),
        ("true", "false"),
        ("correct", "incorrect"),
        ("correct", "wrong"),
        ("right", "wrong"),
        ("pass", "fail"),
        ("pass", "failed"),
        ("passed", "failed"),
        ("valid", "invalid"),
        ("legal", "illegal"),
        ("allowed", "forbidden"),
        ("accept", "reject"),
        ("accepted", "rejected"),
        ("ja", "nein"),
        ("wahr", "falsch"),
        ("richtig", "falsch"),
        ("korrekt", "inkorrekt"),
        ("korrekt", "falsch"),
        ("bestanden", "durchgefallen"),
        ("gültig", "ungültig"),
        ("erlaubt", "verboten"),
    ],
    "direction": [
        ("inside", "outside"),
        ("up", "down"),
        ("left", "right"),
        ("above", "below"),
        ("before", "after"),
        ("increase", "decrease"),
        ("increases", "decreases"),
        ("higher", "lower"),
        ("more", "less"),
        ("more", "fewer"),
        ("ascending", "descending"),
        ("innen", "außen"),
        ("oben", "unten"),
        ("links", "rechts"),
        ("über", "unter"),
        ("vor", "nach"),
        ("steigt", "sinkt"),
        ("steigend", "fallend"),
        ("höher", "niedriger"),
        ("mehr", "weniger"),
        ("aufsteigend", "absteigend"),
    ],
    "sequence": [
        ("first", "second"),
        ("first", "last"),
        ("first", "next"),
        ("most", "second"),
        ("most", "least"),
        ("always", "never"),
        ("all", "none"),
        ("every", "no"),
        ("erste", "zweite"),
        ("erste", "letzte"),
        ("erste", "nächste"),
        ("erster", "zweiter"),
        ("erster", "letzter"),
        ("immer", "nie"),
        ("immer", "niemals"),
        ("alle", "keine"),
        ("meisten", "wenigsten"),
    ],
    "polarity": [
        ("is", "not"),
        ("can", "cannot"),
        ("do", "don"),
        ("does", "doesn"),
        ("will", "won"),
        ("should", "shouldn"),
        ("must", "may"),
        ("ist", "nicht"),
        ("kann", "nicht"),
        ("muss", "darf"),
    ],
}

# Symmetric lookup: normalized token -> set of its lexicon antonyms.
ANTONYMS: dict[str, frozenset[str]] = {}


def _build_antonym_lookup() -> None:
    lookup: dict[str, set[str]] = {}
    for pairs in ANTONYM_CLASSES.values():
        for a, b in pairs:
            lookup.setdefault(a, set()).add(b)
            lookup.setdefault(b, set()).add(a)
    ANTONYMS.update({token: frozenset(v) for token, v in lookup.items()})


_build_antonym_lookup()

# Hedging terms whose presence in the prediction set signals the model was
# tempted to qualify the statement (paper's "speculative terms").
SPECULATIVE_TERMS: frozenset[str] = frozenset(
    {
        # English
        "likely",
        "unlikely",
        "possibly",
        "possible",
        "maybe",
        "perhaps",
        "might",
        "may",
        "could",
        "probably",
        "presumably",
        "apparently",
        "seemingly",
        "conceivably",
        "supposedly",
        "arguably",
        "roughly",
        "approximately",
        # German
        "vielleicht",
        "möglicherweise",
        "möglich",
        "wahrscheinlich",
        "unwahrscheinlich",
        "eventuell",
        "vermutlich",
        "womöglich",
        "könnte",
        "könnten",
        "dürfte",
        "dürften",
        "mutmaßlich",
        "anscheinend",
        "scheinbar",
        "gegebenenfalls",
        "ungefähr",
        "circa",
        "etwa",
    }
)

# Prefixes realizing the paper's "adj/not-adj" antonym class (English and
# German negation morphology; "un-" covers both languages).
NEGATION_PREFIXES: tuple[str, ...] = ("un", "in", "im", "ir", "non", "dis")

# Free-standing negators: their appearance among the candidates for a
# non-negator token flips the polarity of the statement being generated.
STANDALONE_NEGATORS: frozenset[str] = frozenset(
    {"not", "never", "no", "nicht", "kein", "keine", "nie", "niemals"}
)

# BPE/SentencePiece markers that prefix sub-word tokens in raw logprob output.
_BPE_MARKERS = ("Ġ", "▁", "##")

# Minimum stem length for the negation-prefix heuristic, so short noise pairs
# like "in"/"inin" or "on"/"non" are not misread as antonyms.
_MIN_NEGATION_STEM = 3


def normalize_token(token: str) -> str:
    """Normalize a raw BPE token for lexicon comparison.

    Strips whitespace, BPE markers and surrounding punctuation, then
    casefolds. Returns "" for tokens that carry no word content (pure
    punctuation or whitespace), which callers should skip entirely.
    """
    stripped = token.strip()
    for marker in _BPE_MARKERS:
        stripped = stripped.removeprefix(marker)
    stripped = stripped.strip()
    start = 0
    end = len(stripped)
    while start < end and _is_punctuation(stripped[start]):
        start += 1
    while end > start and _is_punctuation(stripped[end - 1]):
        end -= 1
    return stripped[start:end].casefold()


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P")


def are_antonyms(chosen: str, candidate: str) -> bool:
    """Return True if a candidate token contradicts the chosen token.

    Both inputs must already be normalized. Checks the curated lexicon (in
    both directions), the negation-prefix heuristic (certain vs. uncertain,
    gültig vs. ungültig), and — directionally — a standalone negator
    appearing as an alternative to a non-negator chosen token, which signals
    the model considered negating the statement.
    """
    if not chosen or not candidate or chosen == candidate:
        return False

    if candidate in ANTONYMS.get(chosen, frozenset()):
        return True

    for prefix in NEGATION_PREFIXES:
        if candidate == prefix + chosen and len(chosen) >= _MIN_NEGATION_STEM:
            return True
        if chosen == prefix + candidate and len(candidate) >= _MIN_NEGATION_STEM:
            return True

    if candidate in STANDALONE_NEGATORS and chosen not in STANDALONE_NEGATORS:
        return True

    return False


def is_speculative(token: str) -> bool:
    """Return True if the normalized token is a speculative/hedging term."""
    return token in SPECULATIVE_TERMS

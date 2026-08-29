"""Evidence guard for organizational and exam questions.

Answers about *subject matter* can be judged on their merits: a wrong explanation of
the Bridge pattern is visibly wrong and a student can check it against the lecture.
Answers about *the course as an institution* — exam scope, dates, rooms, deadlines,
grading, registration — cannot. They are facts about one specific course in one
specific semester, they are not implied by what the course teaches, and a plausible
invention is indistinguishable from the truth until the student acts on it.

The system prompt tells the model not to invent these (see
``autonomous_tutor_system_prompt.j2``), and the verbalized confidence prompts tell it
to score such answers low. Neither is binding: prompts are followed most of the time,
and in logprob mode the confidence never passes through a prompt at all — a fluent
invention scores *high* there, because the model is not uncertain about its own
wording. This module is the part that does not depend on the model behaving:

    organizational question  +  no tool returned a supporting fact
        ⇒  the confidence is capped below Artemis's auto-publish threshold,
           so a human sees the answer before a student does.

The guard only ever lowers a score. An answer that the model was already unsure about
stays unsure (and is discarded by Artemis as before); an answer that IS grounded in an
FAQ entry or a tutor-verified prior answer is left alone and can still auto-publish.

Detection is a curated bilingual lexicon rather than a classifier call: it costs
nothing, it is deterministic and inspectable (which a thesis evaluation needs), and
its failure mode is the safe one — a false positive sends a subject-matter answer to
tutor review, it never lets an ungrounded exam claim through.
"""

import re

# Terms matched on word boundaries. Kept here when the bare word is ambiguous enough
# that a substring match would fire on unrelated text ("termin" inside "terminal",
# "room" inside "classroom", "note" inside "notation").
_WORD_TERMS: dict[str, tuple[str, ...]] = {
    "exam": (
        "exam",
        "exams",
        "midterm",
        "endterm",
        "retake",
        "retakes",
        "resit",
        "mock exam",
        "final exam",
        "open book",
        "closed book",
        "cheat sheet",
        "allowed aids",
    ),
    "grading": (
        "grade",
        "grades",
        "graded",
        "grading",
        "bonus",
        "ects",
        "credits",
        "credit points",
        "passing mark",
        "pass mark",
        "noten",
        "bestehen",
        "bestanden",
    ),
    "deadline": (
        "deadline",
        "deadlines",
        "due date",
        "due by",
        "cutoff",
        "cut-off",
        "late submission",
        "frist",
        "fristen",
        "termin",
        "termine",
    ),
    "enrollment": (
        "enroll",
        "enrol",
        "enrolled",
        "enrollment",
        "enrolment",
        "registration",
        "deregister",
        "sign up",
        "waiting list",
        "attendance",
    ),
    "schedule": (
        "timetable",
        "syllabus",
        "curriculum",
        "office hours",
        "lecture hall",
        "lecture time",
        "lecture times",
        "lecture timings",
        "tutorial time",
        "tutorial times",
        "course schedule",
        "lecture schedule",
        "exam schedule",
        "room",
        "rooms",
        "raum",
        "räume",
        "uhrzeit",
    ),
}

# Stems matched anywhere in the text. German forms compounds freely — "Klausurtermin",
# "Prüfungsanmeldung", "Abgabefrist", "Vorlesungszeiten" — so a word-boundary match
# would miss exactly the phrasings students actually use.
_STEM_TERMS: dict[str, tuple[str, ...]] = {
    "exam": ("klausur", "pruefung", "prüfung"),
    "grading": (
        "notenschlüssel",
        "notenspiegel",
        "benotung",
        "bewertungsschema",
        "bonuspunkt",
    ),
    "deadline": ("abgabe",),
    "enrollment": ("anmeldung", "abmeldung", "einschreibung", "anwesenheit"),
    "schedule": ("vorlesungszeit", "sprechstunde", "stundenplan", "hörsaal"),
}

# Prefixes that turn a stem into an unrelated everyday word. "Überprüfung" is
# verification, not an exam. Deliberately per-stem: "Nachklausur" and "Nachprüfung"
# are retakes and must still count, so a blanket prefix list would silence exactly
# the questions the guard exists for.
_STEM_PREFIX_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "prüfung": ("über", "ueber"),
    "pruefung": ("über", "ueber"),
}


def _word_pattern(terms: tuple[str, ...]) -> re.Pattern:
    alternatives = "|".join(re.escape(term) for term in terms)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE | re.UNICODE)


def _stem_alternative(term: str) -> str:
    lookbehinds = "".join(
        f"(?<!{prefix})" for prefix in _STEM_PREFIX_EXCLUSIONS.get(term, ())
    )
    return f"{lookbehinds}{re.escape(term)}"


def _stem_pattern(terms: tuple[str, ...]) -> re.Pattern:
    alternatives = "|".join(_stem_alternative(term) for term in terms)
    return re.compile(alternatives, re.IGNORECASE | re.UNICODE)


_WORD_PATTERNS = {
    category: _word_pattern(terms) for category, terms in _WORD_TERMS.items()
}
_STEM_PATTERNS = {
    category: _stem_pattern(terms) for category, terms in _STEM_TERMS.items()
}


def classify_organizational_question(text: str | None) -> str | None:
    """Return the organizational category ``text`` falls into, or ``None``.

    The category is returned rather than a bare boolean so the log line (and the
    thesis evaluation reading those logs) says *why* an answer was held back.
    """
    if not text or not text.strip():
        return None
    for category, pattern in _WORD_PATTERNS.items():
        if pattern.search(text):
            return category
    for category, pattern in _STEM_PATTERNS.items():
        if pattern.search(text):
            return category
    return None


def is_organizational_question(text: str | None) -> bool:
    """Whether ``text`` asks about the course as an institution."""
    return classify_organizational_question(text) is not None


def has_organizational_evidence(faq_hits, memory_hits) -> bool:
    """Whether a tool returned something that can ground an organizational fact.

    Only two sources qualify. The course FAQ is what instructors maintain for exactly
    these questions, and course memory holds answers a tutor verified. Lecture content
    does not qualify: it describes what is taught, and "what the course teaches" is
    precisely the evidence the model keeps mistaking for "what the exam covers". The
    course-details tool does not qualify either — it is always available, so counting
    it would mean the guard never fires.
    """
    return bool(faq_hits) or bool(memory_hits)

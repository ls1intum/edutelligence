"""Deterministic intent planning for authoritative chat evidence."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping

from iris.pipeline.chat.iris_chat_mode import IrisChatMode


@dataclass(frozen=True)
class AuthoritativeEvidencePlan:
    """The product evidence that an explicit user intent requires."""

    exercise_metrics: bool = False
    competencies: bool = False
    faq: bool = False
    submission: bool = False
    build_logs: bool = False
    feedback: bool = False
    repository: bool = False
    lecture: bool = False

    @property
    def active(self) -> bool:
        """Return whether the plan requires at least one evidence source."""
        return any(
            (
                self.exercise_metrics,
                self.competencies,
                self.faq,
                self.submission,
                self.build_logs,
                self.feedback,
                self.repository,
                self.lecture,
            )
        )


_SOCIAL_ONLY = re.compile(
    r"^\s*(?:(?:hi|hello|hey|greetings|hallo|servus|moin|"
    r"guten\s+(?:morgen|tag|abend))(?:\s+iris)?|"
    r"(?:thanks|thank\s+you|danke)(?:\s+iris)?)\s*[,!?.-]*\s*$",
    re.IGNORECASE,
)
_SELF_REFERENCE = re.compile(
    r"\b(?:my|mine|me|i|i'm|i\s+am|mein\w*|mir|mich|ich)\b", re.IGNORECASE
)
_DEFINITIONAL = re.compile(
    r"^\s*(?:what\s+(?:is|are|does)|how\s+(?:do|does)|define|"
    r"explain\s+(?:the\s+)?concept|"
    r"was\s+(?:ist|sind|bedeutet)|definier\w*)\b",
    re.IGNORECASE,
)
_REQUEST_SIGNAL = re.compile(
    r"(?:\?|^\s*(?:(?:please|bitte)\s+)?(?:when|what|which|where|how|why|"
    r"can|could|would|should|"
    r"do|does|is|are|am|may|will|tell|show|compare|analy[sz]e|recommend|"
    r"build|help|interpret|wann|was|welche[rmns]?|wo|wie|warum|kann|"
    r"könnte|würde|sollte|darf|gilt|ist|sind|zeig|vergleich|analysier|"
    r"empfiehl|hilf)|\b(?:need\s+to\s+know|want\s+to\s+know|unsure|"
    r"need|want|would\s+like|wonder\w*|möchte(?:\s+wissen)?|unsicher)\b)",
    re.IGNORECASE,
)
_PERFORMANCE = re.compile(
    r"\b(?:dashboard|learning\s+analytics|metric\w*|score\w*|mark\w*|"
    r"grades?|performance|progress|mastery|trend\w*|class\s+average|"
    r"course\s+average|cohort|keeping\s+up|on\s+track|weak\w*|strong\w*|"
    r"submission\s+tim\w*|timeliness|pace|"
    r"lernanalys\w*|metrik\w*|punkt\w*|noten?|leistung\w*|"
    r"fortschritt\w*|beherrschung\w*|trend\w*|kursdurchschnitt|"
    r"mithalten|schwächer\w*|stärker\w*|abgabezeit\w*)\b",
    re.IGNORECASE,
)
_COMPETENCY = re.compile(r"\b(?:competenc\w*|kompetenz\w*)\b", re.IGNORECASE)
_PERSONAL_PLAN_FROM_DATA = re.compile(
    r"\b(?:study|learning|revision|lern\w*)\s+plan\b.*\b(?:based\s+on|"
    r"using|from|anhand|basierend\s+auf)\b.*\b(?:progress|performance|"
    r"score\w*|fortschritt|leistung|punkt\w*)\b",
    re.IGNORECASE,
)
_OFFICIAL_POLICY = re.compile(
    r"\b(?:deadline|due\s+date|grace\s+period|cut[ -]?off|extension|"
    r"late\s+submission|submit\w*\s+(?:after|late)|graded|practice\s+submission|"
    r"eligib\w*|enrol\w*|registration\s+(?:date|period|deadline)|"
    r"exam\s+(?:date|time|registration)|grading\s+(?:policy|rule)|"
    r"course\s+(?:policy|rule)|official\s+(?:date|rule)|"
    r"abgabefrist|fristverlänger\w*|nachfrist|kulanzfrist|verspät\w*|"
    r"bewert\w*\s+(?:regel\w*|richtlin\w*)|prüfungs?termin|"
    r"anmelde(?:frist|zeitraum)|teilnahmeberechtig\w*)\b",
    re.IGNORECASE,
)
_WHEN_DUE = re.compile(
    r"\b(?:when|what\s+time|welche[rmns]?\s+zeit|wann)\b[^?]{0,80}"
    r"\b(?:due|fällig|abzugeben|abgabe)\b",
    re.IGNORECASE,
)
_COMPETENCY_SOFT_DUE = re.compile(
    r"\b(?:soft\s+due|competenc\w*[^.!?]{0,30}(?:deadline|due)|"
    r"kompetenz\w*[^.!?]{0,30}(?:frist|fällig))\b",
    re.IGNORECASE,
)
_PROGRAM_FAILURE = re.compile(
    r"\b(?:does(?:n't|\s+not)\s+(?:compile|work)|won't\s+compile|"
    r"(?:submission|code|solution|implementation|program|build|test\w*)"
    r"(?:\s+\w+){0,2}\s+(?:fail\w*|reject\w*)|"
    r"compiler\s+error\w*|build\s+(?:error|failure|failed)|"
    r"hidden\s+test|public\s+test|"
    r"wrong\s+(?:output|result|position)|incorrect\s+(?:output|result)|"
    r"(?:output|result|behavio\w*)\s+(?:is\s+)?unchanged|"
    r"off[ -]?by[ -]?one|bug\w*|debug\w*|diagnos\w*|"
    r"crash\w*|build\s+log\w*|kompilier\w*\s+nicht|compilerfehler\w*|"
    r"buildfehler\w*|test\w*\s+(?:schlägt|fehlschlägt)|falsch\w*\s+"
    r"(?:ausgabe|ergebnis)|(?:ausgabe|ergebnis)\s+unverändert|fehlersuch\w*)\b",
    re.IGNORECASE,
)
_PERSONAL_CODE = re.compile(
    r"\b(?:my|mein\w*)\s+(?:code|submission|solution|implementation|"
    r"output|result|build|test\w*|repository|repo|file\w*|abgabe|lösung|"
    r"implementierung|ausgabe|ergebnis|datei\w*)\b",
    re.IGNORECASE,
)
_CODE_INVESTIGATION = re.compile(
    r"\b(?:trace|inspect|review|analy[sz]e|investigate|debug|diagnose|"
    r"find|fix|resolve|why|stuck|nachvollzieh\w*|untersuch\w*|prüf\w*|"
    r"analysier\w*|finde\w*|beheb\w*|warum)\b",
    re.IGNORECASE,
)
_SUBMISSION_VISIBILITY = re.compile(
    r"\b(?:uncommitted|not\s+committed|did\s+not\s+commit|"
    r"without\s+committing|latest\s+submission|"
    r"submitted\s+(?:code|version|file\w*)|(?:what|which)\s+"
    r"(?:code|version|submission)"
    r"[^?]{0,60}(?:see|inspect|access)|(?:can|could|do)\s+you\s+"
    r"(?:see|inspect|access|read|view)[^?]{0,60}(?:change|code|file|repo|"
    r"submission|version)|nicht\s+(?:committed|committet\w*|eingecheckt)|"
    r"letzte\s+abgabe|"
    r"eingereichte\s+(?:version|datei\w*|code)|welche\s+(?:version|abgabe)"
    r"[^?]{0,60}(?:sehen|prüfen|zugreifen))\b",
    re.IGNORECASE,
)
_BUILD_DIAGNOSTIC = re.compile(
    r"\b(?:build|compil\w*|compiler|syntax\s+error|build\s+log|"
    r"kompilier\w*|compilerfehler|buildfehler|syntaxfehler)\b",
    re.IGNORECASE,
)
_LECTURE_SCOPE = re.compile(
    r"\b(?:lecture|slide\w*|section|chapter|transcript|recording|video|"
    r"recurrence[ -]?tree|master\s+theorem|vorlesung|folie\w*|abschnitt|"
    r"kapitel|transkript|aufzeichnung|video)\b",
    re.IGNORECASE,
)
_LECTURE_COMPARISON = re.compile(
    r"\b(?:compare|contrast|connect|relate|across|vergleich\w*|gegenüberstell\w*|"
    r"verknüpf\w*|zusammenhang)\b",
    re.IGNORECASE,
)
_CURRENT_VIEW_REFERENCE = re.compile(
    r"\b(?:this|current|visible|shown|here|diese[rmns]?|aktuell\w*|"
    r"sichtbar\w*|hier)\b[^.!?]{0,40}\b(?:slide|page|video|folie|seite)\b|"
    r"\b(?:on\s+(?:this|the)\s+slide|in\s+(?:this|the)\s+video|"
    r"auf\s+dieser\s+folie)\b",
    re.IGNORECASE,
)
_EXTERNAL_LECTURE_SCOPE = re.compile(
    r"\b(?:section|chapter|elsewhere|other\s+(?:slide|part)|beyond|"
    r"abschnitt|kapitel|andere[rmns]?\s+(?:folie|teil)|weiter\w*)\b",
    re.IGNORECASE,
)
_LECTURE_REASONING_SUBJECT = re.compile(
    r"\b(?:formula\w*|result\w*|recurrence\w*|equation\w*|theorem\w*|"
    r"proof\w*|argument\w*|conclusion\w*|complexit\w*|bound\w*|claim\w*|"
    r"identity|formel\w*|ergebnis\w*|rekurrenz\w*|gleichung\w*|satz|sätze|"
    r"theorem\w*|beweis\w*|argument\w*|schlussfolger\w*|komplexität\w*|"
    r"schranke\w*|aussage\w*|identität\w*)\b",
    re.IGNORECASE,
)
_LECTURE_WHY = re.compile(
    r"\b(?:why|warum|wieso|weshalb)\b",
    re.IGNORECASE,
)
_LECTURE_EXPLANATION_ACTION = re.compile(
    r"\b(?:explain\w*|deriv\w*|reasoning|justify\w*|prove\w*|"
    r"erklär\w*|herleit\w*|ableit\w*|begründ\w*|nachvollzieh\w*)\b",
    re.IGNORECASE,
)
_LECTURE_HOW_REASONING = re.compile(
    r"\b(?:how|wie)\b[^.!?\n]{0,120}\b(?:follow\w*|deriv\w*|work\w*|"
    r"obtain\w*|arrive\w*|lead\w*|reason\w*|become\w*|transform\w*|"
    r"yield\w*|impl(?:y|ies|ied)|produce\w*|folgt\w*|hergeleit\w*|"
    r"funktionier\w*|entsteh\w*|zustande|komm\w*|ableit\w*|werd\w*|"
    r"umform\w*|übergeh\w*|führ\w*|ergib\w*)\b",
    re.IGNORECASE,
)
_FUNCTION_EQUATION = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_]*\s*\([^()\n]{1,50}\)\s*"
    r"(?:=|<=|>=|≠|≈|≤|≥|\\(?:le|ge|approx|sim))",
)
_INDEXED_EQUATION = re.compile(
    r"\b[A-Za-z](?:_\{?[A-Za-z0-9+\-]+\}?|\[[^\]\n]{1,30}\])\s*"
    r"(?:=|<=|>=|≠|≈|≤|≥|\\(?:le|ge|approx|sim))",
)
_ASYMPTOTIC_NOTATION = re.compile(
    r"(?<!\w)(?:[OΘΩ]|\\(?:Theta|Omega|mathcal\s*\{O\}))\s*" r"\([^()\n]{1,80}\)",
)
_LATEX_VARIABLE_EXPRESSION = re.compile(
    r"(?:\\\(|\\\[|\$)[^\n$]{0,120}"
    r"(?:(?<!\\)\b[A-Za-z]\b|\\(?:Theta|Omega|mathcal|sum|prod|lim|log))"
    r"[^\n$]{0,120}(?:=|\\(?:le|ge|approx|sim)|\^|_)"
    r"[^\n$]{0,120}(?:\\\)|\\\]|\$)",
)

_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".hs",
    ".java",
    ".js",
    ".kt",
    ".kts",
    ".m",
    ".ml",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
}
_GENERATED_PATH_PARTS = {
    ".git",
    ".gradle",
    ".idea",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


def _has_lecture_math_expression(text: str) -> bool:
    """Recognize structured notation without treating bare arithmetic as scope."""

    return any(
        pattern.search(text)
        for pattern in (
            _FUNCTION_EQUATION,
            _INDEXED_EQUATION,
            _ASYMPTOTIC_NOTATION,
            _LATEX_VARIABLE_EXPRESSION,
        )
    )


def is_submission_visibility_intent(query: str) -> bool:
    """Return whether the user asks which submitted/local version Iris can see."""

    return bool(_SUBMISSION_VISIBILITY.search(query or ""))


def plan_authoritative_evidence(
    query: str,
    chat_mode: IrisChatMode,
    *,
    event: str | None = None,
    mcq_requested: bool = False,
    has_current_view: bool = False,
) -> AuthoritativeEvidencePlan:
    """Plan evidence from explicit product intent without an additional model call."""
    text = (query or "").strip()
    if not text or mcq_requested or _SOCIAL_ONLY.fullmatch(text):
        return AuthoritativeEvidencePlan()

    performance = False
    competencies = False
    lecture = False
    if chat_mode is IrisChatMode.LECTURE:
        request_signal = bool(_REQUEST_SIGNAL.search(text))
        lecture_scope = bool(_LECTURE_SCOPE.search(text))
        comparison = bool(_LECTURE_COMPARISON.search(text))
        reasoning_subject = bool(
            _LECTURE_REASONING_SUBJECT.search(text)
            or _has_lecture_math_expression(text)
        )
        reasoning_intent = bool(
            reasoning_subject
            and (
                _LECTURE_WHY.search(text)
                or _LECTURE_EXPLANATION_ACTION.search(text)
                or _LECTURE_HOW_REASONING.search(text)
            )
        )
        current_view_only = bool(
            has_current_view
            and _CURRENT_VIEW_REFERENCE.search(text)
            and not _EXTERNAL_LECTURE_SCOPE.search(text)
            and not reasoning_intent
        )
        lecture = bool(
            request_signal
            and (lecture_scope or reasoning_intent)
            and (reasoning_intent or comparison or not has_current_view)
            and not current_view_only
        )
    if chat_mode is IrisChatMode.COURSE:
        request_signal = bool(_REQUEST_SIGNAL.search(text))
        performance = bool(
            request_signal
            and (_SELF_REFERENCE.search(text) or "dashboard" in text.casefold())
            and (_PERFORMANCE.search(text) or _PERSONAL_PLAN_FROM_DATA.search(text))
        )
        competency_mention = bool(_COMPETENCY.search(text))
        competencies = performance or bool(
            competency_mention
            and request_signal
            and not (_DEFINITIONAL.search(text) and not _SELF_REFERENCE.search(text))
        )

    faq = (
        chat_mode is not IrisChatMode.LECTURE
        and bool(_REQUEST_SIGNAL.search(text))
        and bool(_OFFICIAL_POLICY.search(text) or _WHEN_DUE.search(text))
    )
    if (
        faq
        and _COMPETENCY_SOFT_DUE.search(text)
        and not re.search(
            r"\b(?:grace|graded|practice|extension|policy|rule|nachfrist|kulanz)\b",
            text,
            re.IGNORECASE,
        )
    ):
        faq = False

    diagnostic = False
    visibility = False
    build_logs = False
    if chat_mode is IrisChatMode.EXERCISE:
        event_diagnostic = event in {"build_failed", "progress_stalled"}
        failure_signal = bool(_PROGRAM_FAILURE.search(text))
        personal_investigation = bool(
            _PERSONAL_CODE.search(text) and _CODE_INVESTIGATION.search(text)
        )
        conceptual = bool(
            _DEFINITIONAL.search(text) and not _PERSONAL_CODE.search(text)
        )
        diagnostic = event_diagnostic or (
            (failure_signal or personal_investigation) and not conceptual
        )
        visibility = is_submission_visibility_intent(text)
        build_logs = diagnostic and bool(
            event == "build_failed" or _BUILD_DIAGNOSTIC.search(text)
        )

    submission_evidence = diagnostic or visibility
    return AuthoritativeEvidencePlan(
        exercise_metrics=performance,
        competencies=competencies,
        faq=faq,
        submission=submission_evidence,
        build_logs=build_logs,
        feedback=diagnostic,
        repository=submission_evidence,
        lecture=lecture,
    )


def select_repository_files(
    query: str,
    repository: Mapping[str, str],
    *,
    limit: int = 2,
) -> list[str]:
    """Select a small set of likely relevant submitted source files."""
    if limit <= 0:
        return []
    folded_query = (query or "").casefold()
    query_terms = set(re.findall(r"[\w.-]+", folded_query))
    ranked: list[tuple[int, int, str]] = []
    for path, content in repository.items():
        normalized = path.replace("\\", "/")
        parsed = PurePosixPath(normalized)
        parts = {part.casefold() for part in parsed.parts}
        if parts & _GENERATED_PATH_PARTS or not content:
            continue
        suffix = parsed.suffix.casefold()
        basename = parsed.name.casefold()
        stem = parsed.stem.casefold()
        score = 0
        if normalized.casefold() in folded_query or basename in folded_query:
            score += 100
        if stem and stem in query_terms:
            score += 60
        if suffix in _SOURCE_EXTENSIONS:
            score += 30
        if "src" in parts:
            score += 15
        if any(part in {"test", "tests"} for part in parts):
            score -= 10
        if suffix not in _SOURCE_EXTENSIONS:
            score -= 20
        ranked.append((score, -len(content), normalized))

    ranked.sort(key=lambda item: (-item[0], -item[1], item[2].casefold()))
    return [path for score, _, path in ranked[:limit] if score >= 0]

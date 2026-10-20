import pytest

from iris.domain.data.course_dto import CourseDTO

# The values of the ProgrammingLanguage enum in Artemis, which sends the course's default
# programming language by name. Keep in sync when Artemis adds a language.
ARTEMIS_PROGRAMMING_LANGUAGES = [
    "EMPTY",
    "JAVA",
    "PYTHON",
    "C",
    "HASKELL",
    "KOTLIN",
    "VHDL",
    "ASSEMBLER",
    "SWIFT",
    "OCAML",
    "JAVASCRIPT",
    "C_SHARP",
    "C_PLUS_PLUS",
    "SQL",
    "R",
    "TYPESCRIPT",
    "RUST",
    "GO",
    "MATLAB",
    "BASH",
    "RUBY",
    "POWERSHELL",
    "ADA",
    "DART",
    "PHP",
]


@pytest.mark.parametrize("language", ARTEMIS_PROGRAMMING_LANGUAGES)
def test_course_accepts_every_artemis_programming_language(language):
    course = CourseDTO.model_validate({"id": 1, "defaultProgrammingLanguage": language})
    assert course.default_programming_language == language


def test_course_accepts_a_language_added_to_artemis_later():
    course = CourseDTO.model_validate(
        {"id": 1, "defaultProgrammingLanguage": "SOME_FUTURE_LANGUAGE"}
    )
    assert course.default_programming_language == "SOME_FUTURE_LANGUAGE"


@pytest.mark.parametrize(
    "payload", [{"id": 1}, {"id": 1, "defaultProgrammingLanguage": None}]
)
def test_course_without_a_default_programming_language_stays_valid(payload):
    assert CourseDTO.model_validate(payload).default_programming_language is None

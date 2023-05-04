from pydantic import Field, AnyUrl

from . import ExerciseType, Exercise


class ProgrammingExercise(Exercise):
    """A programming exercise that can be solved by students, enhanced with metadata."""

    type: ExerciseType = Field(ExerciseType.programming, const=True)

    programming_language: str = Field(description="The programming language that is used for this exercise.", example="java")
    solution_repository_url: AnyUrl = Field(description="URL to the solution git repository, which contains the reference solution.",
                                            example="http://localhost:3000/api/example-solutions/1")
    template_repository_url: AnyUrl = Field(description="URL to the template git repository, which is the starting point for students.",
                                            example="http://localhost:3000/api/example-template/1")
    tests_repository_url: AnyUrl = Field(description="URL to the tests git repository, which contains the tests that are used to automatically grade the exercise.",
                                         example="http://localhost:3000/api/example-tests/1")

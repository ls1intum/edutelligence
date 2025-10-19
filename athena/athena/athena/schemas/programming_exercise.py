from pydantic import Field, AnyUrl, field_serializer
from typing import Literal
from zipfile import ZipFile
from git.repo import Repo

from athena.helpers.programming.code_repository import get_repository_zip, get_repository
from .exercise_type import ExerciseType
from .exercise import Exercise
from typing import Literal


class ProgrammingExercise(Exercise):
    """A programming exercise that can be solved by students, enhanced with metadata."""

    type: Literal[ExerciseType.programming] = ExerciseType.programming

    programming_language: str = Field(description="The programming language that is used for this exercise.", examples=["java"])
    solution_repository_uri: AnyUrl = Field(description="URL to the solution git repository, which contains the "
                                                        "reference solution.",
                                            examples=["http://localhost:3000/api/example-solutions/1"])
    template_repository_uri: AnyUrl = Field(description="URL to the template git repository, which is the starting "
                                                        "point for students.",
                                            examples=["http://localhost:3000/api/example-template/1"])
    tests_repository_uri: AnyUrl = Field(description="URL to the tests git repository, which contains the tests that "
                                                     "are used to automatically grade the exercise.",
                                         examples=["http://localhost:3000/api/example-tests/1"])


    def get_solution_zip(self) -> ZipFile:
        """Return the solution repository as a ZipFile object."""
        return get_repository_zip(str(self.solution_repository_uri))


    def get_solution_repository(self) -> Repo:
        """Return the solution repository as a Repo object."""
        return get_repository(str(self.solution_repository_uri))


    def get_template_zip(self) -> ZipFile:
        """Return the template repository as a ZipFile object."""
        return get_repository_zip(str(self.template_repository_uri))


    def get_template_repository(self) -> Repo:
        """Return the template repository as a Repo object."""
        return get_repository(str(self.template_repository_uri))


    def get_tests_zip(self) -> ZipFile:
        """Return the tests repository as a ZipFile object."""
        return get_repository_zip(str(self.tests_repository_uri))


    def get_tests_repository(self) -> Repo:
        """Return the tests repository as a Repo object."""
        return get_repository(str(self.tests_repository_uri))
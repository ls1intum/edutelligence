from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ProgrammingLanguage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EMPTY: _ClassVar[ProgrammingLanguage]
    JAVA: _ClassVar[ProgrammingLanguage]
    PYTHON: _ClassVar[ProgrammingLanguage]

class ProjectType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PLAIN: _ClassVar[ProjectType]
    MAVEN: _ClassVar[ProjectType]
    GRADLE: _ClassVar[ProjectType]

EMPTY: ProgrammingLanguage
JAVA: ProgrammingLanguage
PYTHON: ProgrammingLanguage
PLAIN: ProjectType
MAVEN: ProjectType
GRADLE: ProjectType

class ProgrammingExercise(_message.Message):
    __slots__ = (
        "id",
        "template_repository",
        "solution_repository",
        "test_repository",
        "problem_statement",
        "boundary_conditions",
    )
    ID_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    id: int
    template_repository: Repository
    solution_repository: Repository
    test_repository: Repository
    problem_statement: ProblemStatement
    boundary_conditions: BoundaryConditions
    def __init__(
        self,
        id: _Optional[int] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
    ) -> None: ...

class Repository(_message.Message):
    __slots__ = ("name", "files")
    NAME_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    name: str
    files: _containers.RepeatedCompositeFieldContainer[RepositoryFile]
    def __init__(
        self,
        name: _Optional[str] = ...,
        files: _Optional[_Iterable[_Union[RepositoryFile, _Mapping]]] = ...,
    ) -> None: ...

class RepositoryFile(_message.Message):
    __slots__ = ("path", "content")
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    path: str
    content: str
    def __init__(
        self, path: _Optional[str] = ..., content: _Optional[str] = ...
    ) -> None: ...

class ProblemStatement(_message.Message):
    __slots__ = ("title", "short_title", "description")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SHORT_TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    title: str
    short_title: str
    description: str
    def __init__(
        self,
        title: _Optional[str] = ...,
        short_title: _Optional[str] = ...,
        description: _Optional[str] = ...,
    ) -> None: ...

class BoundaryConditions(_message.Message):
    __slots__ = (
        "language",
        "technical_environment",
        "project_type",
        "programming_language",
        "difficulty",
        "points",
        "bonus_points",
        "constraints",
    )
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    TECHNICAL_ENVIRONMENT_FIELD_NUMBER: _ClassVar[int]
    PROJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    PROGRAMMING_LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    DIFFICULTY_FIELD_NUMBER: _ClassVar[int]
    POINTS_FIELD_NUMBER: _ClassVar[int]
    BONUS_POINTS_FIELD_NUMBER: _ClassVar[int]
    CONSTRAINTS_FIELD_NUMBER: _ClassVar[int]
    language: str
    technical_environment: str
    project_type: ProjectType
    programming_language: ProgrammingLanguage
    difficulty: str
    points: int
    bonus_points: int
    constraints: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        language: _Optional[str] = ...,
        technical_environment: _Optional[str] = ...,
        project_type: _Optional[_Union[ProjectType, str]] = ...,
        programming_language: _Optional[_Union[ProgrammingLanguage, str]] = ...,
        difficulty: _Optional[str] = ...,
        points: _Optional[int] = ...,
        bonus_points: _Optional[int] = ...,
        constraints: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class PingRequest(_message.Message):
    __slots__ = ("client_id",)
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    client_id: str
    def __init__(self, client_id: _Optional[str] = ...) -> None: ...

class PingResponse(_message.Message):
    __slots__ = ("status", "version", "timestamp")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    status: str
    version: str
    timestamp: int
    def __init__(
        self,
        status: _Optional[str] = ...,
        version: _Optional[str] = ...,
        timestamp: _Optional[int] = ...,
    ) -> None: ...

class BoundaryConditionsDefinerRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BoundaryConditionsDefinerResponse(_message.Message):
    __slots__ = ("boundary_conditions",)
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    def __init__(
        self, boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...
    ) -> None: ...

class ProblemStatementDrafterRequest(_message.Message):
    __slots__ = ("boundary_conditions",)
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    def __init__(
        self, boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...
    ) -> None: ...

class ProblemStatementDrafterResponse(_message.Message):
    __slots__ = ("boundary_conditions", "problem_statement")
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
    ) -> None: ...

class SolutionRepositoryCreatorRequest(_message.Message):
    __slots__ = ("boundary_conditions", "problem_statement")
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
    ) -> None: ...

class SolutionRepositoryCreatorResponse(_message.Message):
    __slots__ = ("boundary_conditions", "problem_statement", "solution_repository")
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class TemplateRepositoryCreatorRequest(_message.Message):
    __slots__ = ("boundary_conditions", "problem_statement", "solution_repository")
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class TemplateRepositoryCreatorResponse(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class TestRepositoryCreatorRequest(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class TestRepositoryCreatorResponse(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class ProblemStatementFinalizerRequest(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class ProblemStatementFinalizerResponse(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class GradingConfiguratorRequest(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class GradingConfiguratorResponse(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class InconsistencyCheckRequest(_message.Message):
    __slots__ = (
        "boundary_conditions",
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    BOUNDARY_CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    boundary_conditions: BoundaryConditions
    problem_statement: ProblemStatement
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        boundary_conditions: _Optional[_Union[BoundaryConditions, _Mapping]] = ...,
        problem_statement: _Optional[_Union[ProblemStatement, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class InconsistencyCheckResponse(_message.Message):
    __slots__ = ("inconsistencies",)
    INCONSISTENCIES_FIELD_NUMBER: _ClassVar[int]
    inconsistencies: str
    def __init__(self, inconsistencies: _Optional[str] = ...) -> None: ...
class InconsistencyCheckResponse(_message.Message):
    __slots__ = ("inconsistencies",)
    INCONSISTENCIES_FIELD_NUMBER: _ClassVar[int]
    inconsistencies: str
    def __init__(self, inconsistencies: _Optional[str] = ...) -> None: ...

class RewriteProblemStatementRequest(_message.Message):
    __slots__ = ("text",)
    TEXT_FIELD_NUMBER: _ClassVar[int]
    text: str
    def __init__(self, text: _Optional[str] = ...) -> None: ...

class RewriteProblemStatementResponse(_message.Message):
    __slots__ = ("rewritten_text",)
    REWRITTEN_TEXT_FIELD_NUMBER: _ClassVar[int]
    rewritten_text: str
    def __init__(self, rewritten_text: _Optional[str] = ...) -> None: ...

from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import (
    ClassVar as _ClassVar,
    Iterable as _Iterable,
    Mapping as _Mapping,
    Optional as _Optional,
    Union as _Union,
)

DESCRIPTOR: _descriptor.FileDescriptor

class ProgrammingLanguage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EMPTY: _ClassVar[ProgrammingLanguage]
    ASSEMBLER: _ClassVar[ProgrammingLanguage]
    BASH: _ClassVar[ProgrammingLanguage]
    C: _ClassVar[ProgrammingLanguage]
    C_PLUS_PLUS: _ClassVar[ProgrammingLanguage]
    C_SHARP: _ClassVar[ProgrammingLanguage]
    DART: _ClassVar[ProgrammingLanguage]
    GO: _ClassVar[ProgrammingLanguage]
    HASKELL: _ClassVar[ProgrammingLanguage]
    JAVA: _ClassVar[ProgrammingLanguage]
    JAVASCRIPT: _ClassVar[ProgrammingLanguage]
    KOTLIN: _ClassVar[ProgrammingLanguage]
    MATLAB: _ClassVar[ProgrammingLanguage]
    OCAML: _ClassVar[ProgrammingLanguage]
    PYTHON: _ClassVar[ProgrammingLanguage]
    R: _ClassVar[ProgrammingLanguage]
    RUBY: _ClassVar[ProgrammingLanguage]
    RUST: _ClassVar[ProgrammingLanguage]
    SWIFT: _ClassVar[ProgrammingLanguage]
    TYPESCRIPT: _ClassVar[ProgrammingLanguage]
    VHDL: _ClassVar[ProgrammingLanguage]

class ProjectType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MAVEN_MAVEN: _ClassVar[ProjectType]
    PLAIN_MAVEN: _ClassVar[ProjectType]
    MAVEN_BLACKBOX: _ClassVar[ProjectType]
    PLAIN_GRADLE: _ClassVar[ProjectType]
    GRADLE_GRADLE: _ClassVar[ProjectType]
    PLAIN: _ClassVar[ProjectType]
    XCODE: _ClassVar[ProjectType]
    FACT: _ClassVar[ProjectType]
    GCC: _ClassVar[ProjectType]

EMPTY: ProgrammingLanguage
ASSEMBLER: ProgrammingLanguage
BASH: ProgrammingLanguage
C: ProgrammingLanguage
C_PLUS_PLUS: ProgrammingLanguage
C_SHARP: ProgrammingLanguage
DART: ProgrammingLanguage
GO: ProgrammingLanguage
HASKELL: ProgrammingLanguage
JAVA: ProgrammingLanguage
JAVASCRIPT: ProgrammingLanguage
KOTLIN: ProgrammingLanguage
MATLAB: ProgrammingLanguage
OCAML: ProgrammingLanguage
PYTHON: ProgrammingLanguage
R: ProgrammingLanguage
RUBY: ProgrammingLanguage
RUST: ProgrammingLanguage
SWIFT: ProgrammingLanguage
TYPESCRIPT: ProgrammingLanguage
VHDL: ProgrammingLanguage
MAVEN_MAVEN: ProjectType
PLAIN_MAVEN: ProjectType
MAVEN_BLACKBOX: ProjectType
PLAIN_GRADLE: ProjectType
GRADLE_GRADLE: ProjectType
PLAIN: ProjectType
XCODE: ProjectType
FACT: ProjectType
GCC: ProjectType

class RepositoryFile(_message.Message):
    __slots__ = ("path", "content")
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    path: str
    content: str
    def __init__(
        self, path: _Optional[str] = ..., content: _Optional[str] = ...
    ) -> None: ...

class Repository(_message.Message):
    __slots__ = ("files",)
    FILES_FIELD_NUMBER: _ClassVar[int]
    files: _containers.RepeatedCompositeFieldContainer[RepositoryFile]
    def __init__(
        self, files: _Optional[_Iterable[_Union[RepositoryFile, _Mapping]]] = ...
    ) -> None: ...

class ProgrammingExercise(_message.Message):
    __slots__ = (
        "id",
        "title",
        "programming_language",
        "package_name",
        "project_type",
        "template_repository",
        "solution_repository",
        "test_repository",
        "problem_statement",
    )
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    PROGRAMMING_LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    id: int
    title: str
    programming_language: ProgrammingLanguage
    package_name: str
    project_type: ProjectType
    template_repository: Repository
    solution_repository: Repository
    test_repository: Repository
    problem_statement: str
    def __init__(
        self,
        id: _Optional[int] = ...,
        title: _Optional[str] = ...,
        programming_language: _Optional[_Union[ProgrammingLanguage, str]] = ...,
        package_name: _Optional[str] = ...,
        project_type: _Optional[_Union[ProjectType, str]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        problem_statement: _Optional[str] = ...,
    ) -> None: ...

class InconsistencyCheckRequest(_message.Message):
    __slots__ = (
        "problem_statement",
        "solution_repository",
        "template_repository",
        "test_repository",
    )
    PROBLEM_STATEMENT_FIELD_NUMBER: _ClassVar[int]
    SOLUTION_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    TEST_REPOSITORY_FIELD_NUMBER: _ClassVar[int]
    problem_statement: str
    solution_repository: Repository
    template_repository: Repository
    test_repository: Repository
    def __init__(
        self,
        problem_statement: _Optional[str] = ...,
        solution_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        template_repository: _Optional[_Union[Repository, _Mapping]] = ...,
        test_repository: _Optional[_Union[Repository, _Mapping]] = ...,
    ) -> None: ...

class InconsistencyCheckResponse(_message.Message):
    __slots__ = ("inconsistencies",)
    INCONSISTENCIES_FIELD_NUMBER: _ClassVar[int]
    inconsistencies: str
    def __init__(self, inconsistencies: _Optional[str] = ...) -> None: ...

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

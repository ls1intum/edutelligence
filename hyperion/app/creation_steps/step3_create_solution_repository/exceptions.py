"""Custom exceptions for Step 3: Create Solution Repository."""

from typing import List, Optional, Dict, Any
from ..exceptions import CreationStepException


class SolutionCreatorException(CreationStepException):
    """Base exception for solution creation errors."""

    pass


class CompilationException(SolutionCreatorException):
    """Exception raised for compilation errors."""

    def __init__(
        self,
        message: str,
        compilation_errors: List[str],
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.compilation_errors = compilation_errors


class TestExecutionException(SolutionCreatorException):
    """Exception raised for test execution errors."""

    def __init__(
        self,
        message: str,
        test_failures: List[str],
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.test_failures = test_failures


class LanguageHandlerException(SolutionCreatorException):
    """Exception raised for language handler errors."""

    def __init__(
        self, message: str, language: str, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, details)
        self.language = language


class MaxIterationsExceededException(SolutionCreatorException):
    """Exception raised when maximum iterations are exceeded."""

    def __init__(
        self, message: str, iterations: int, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, details)
        self.iterations = iterations


class TimeoutException(SolutionCreatorException):
    """Exception raised for timeout errors."""

    def __init__(
        self,
        message: str,
        timeout_seconds: int,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.timeout_seconds = timeout_seconds


class CodeGenerationException(SolutionCreatorException):
    """Exception raised for code generation errors."""

    def __init__(
        self,
        message: str,
        generation_step: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.generation_step = generation_step

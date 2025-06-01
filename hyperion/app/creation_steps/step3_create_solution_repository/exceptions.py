"""Custom exceptions for Step 3: Create Solution Repository."""

from typing import List, Optional, Dict, Any


class SolutionCreatorException(Exception):
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class WorkspaceException(SolutionCreatorException):
    pass


class CompilationException(SolutionCreatorException):
    
    def __init__(self, message: str, compilation_errors: List[str], details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.compilation_errors = compilation_errors


class TestExecutionException(SolutionCreatorException):
    
    def __init__(self, message: str, test_failures: List[str], details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.test_failures = test_failures


class LanguageHandlerException(SolutionCreatorException):

    def __init__(self, message: str, language: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.language = language


class MaxIterationsExceededException(SolutionCreatorException):
    
    def __init__(self, message: str, iterations: int, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.iterations = iterations


class TimeoutException(SolutionCreatorException):
    
    def __init__(self, message: str, timeout_seconds: int, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.timeout_seconds = timeout_seconds


class GitException(SolutionCreatorException):
    pass


class FileSystemException(SolutionCreatorException):
    
    def __init__(self, message: str, file_path: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.file_path = file_path


class CodeGenerationException(SolutionCreatorException):
    
    def __init__(self, message: str, generation_step: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)
        self.generation_step = generation_step 
"""Unit tests for Step 3 exceptions."""

import pytest

from ..exceptions import (
    SolutionCreatorException,
    WorkspaceException,
    CompilationException,
    TestExecutionException,
    LanguageHandlerException,
    MaxIterationsExceededException,
    TimeoutException,
    GitException,
    FileSystemException,
    CodeGenerationException
)


class TestSolutionCreatorException:
    """Test SolutionCreatorException base class."""
    
    def test_exception_initialization_message_only(self):
        """Test exception initialization with message only."""
        exc = SolutionCreatorException("Test error message")
        
        assert str(exc) == "Test error message"
        assert exc.message == "Test error message"
        assert exc.details == {}
    
    def test_exception_initialization_with_details(self):
        """Test exception initialization with message and details."""
        details = {"step": "planning", "iteration": 1}
        exc = SolutionCreatorException("Test error", details=details)
        
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
        assert exc.details == details
    
    def test_exception_inheritance(self):
        """Test that SolutionCreatorException inherits from Exception."""
        exc = SolutionCreatorException("Test")
        assert isinstance(exc, Exception)


class TestWorkspaceException:
    """Test WorkspaceException."""
    
    def test_workspace_exception_initialization(self):
        """Test workspace exception initialization."""
        exc = WorkspaceException("Workspace creation failed")
        
        assert str(exc) == "Workspace creation failed"
        assert exc.message == "Workspace creation failed"
        assert isinstance(exc, SolutionCreatorException)
    
    def test_workspace_exception_with_details(self):
        """Test workspace exception with details."""
        details = {"workspace_path": "/tmp/test", "error_code": 1}
        exc = WorkspaceException("Workspace error", details=details)
        
        assert exc.details == details


class TestCompilationException:
    """Test CompilationException."""
    
    def test_compilation_exception_initialization(self):
        """Test compilation exception initialization."""
        compilation_errors = ["Syntax error on line 5", "Missing import on line 1"]
        exc = CompilationException("Compilation failed", compilation_errors)
        
        assert str(exc) == "Compilation failed"
        assert exc.message == "Compilation failed"
        assert exc.compilation_errors == compilation_errors
        assert isinstance(exc, SolutionCreatorException)
    
    def test_compilation_exception_with_details(self):
        """Test compilation exception with details."""
        compilation_errors = ["Error 1", "Error 2"]
        details = {"file": "main.py", "compiler": "python"}
        exc = CompilationException("Compilation failed", compilation_errors, details=details)
        
        assert exc.compilation_errors == compilation_errors
        assert exc.details == details


class TestTestExecutionException:
    """Test TestExecutionException."""
    
    def test_test_execution_exception_initialization(self):
        """Test test execution exception initialization."""
        test_failures = ["test_binary_search failed", "test_edge_case failed"]
        exc = TestExecutionException("Tests failed", test_failures)
        
        assert str(exc) == "Tests failed"
        assert exc.message == "Tests failed"
        assert exc.test_failures == test_failures
        assert isinstance(exc, SolutionCreatorException)
    
    def test_test_execution_exception_with_details(self):
        """Test test execution exception with details."""
        test_failures = ["Test 1 failed", "Test 2 failed"]
        details = {"test_framework": "pytest", "total_tests": 10}
        exc = TestExecutionException("Tests failed", test_failures, details=details)
        
        assert exc.test_failures == test_failures
        assert exc.details == details


class TestLanguageHandlerException:
    """Test LanguageHandlerException."""
    
    def test_language_handler_exception_initialization(self):
        """Test language handler exception initialization."""
        exc = LanguageHandlerException("Language not supported", "UNSUPPORTED_LANG")
        
        assert str(exc) == "Language not supported"
        assert exc.message == "Language not supported"
        assert exc.language == "UNSUPPORTED_LANG"
        assert isinstance(exc, SolutionCreatorException)
    
    def test_language_handler_exception_with_details(self):
        """Test language handler exception with details."""
        details = {"supported_languages": ["PYTHON"], "requested_feature": "compilation"}
        exc = LanguageHandlerException("Feature not supported", "PYTHON", details=details)
        
        assert exc.language == "PYTHON"
        assert exc.details == details


class TestMaxIterationsExceededException:
    """Test MaxIterationsExceededException."""
    
    def test_max_iterations_exception_initialization(self):
        """Test max iterations exception initialization."""
        exc = MaxIterationsExceededException("Maximum iterations reached", 5)
        
        assert str(exc) == "Maximum iterations reached"
        assert exc.message == "Maximum iterations reached"
        assert exc.iterations == 5
        assert isinstance(exc, SolutionCreatorException)
    
    def test_max_iterations_exception_with_details(self):
        """Test max iterations exception with details."""
        details = {"phase": "validation", "last_error": "Compilation failed"}
        exc = MaxIterationsExceededException("Max iterations exceeded", 10, details=details)
        
        assert exc.iterations == 10
        assert exc.details == details


class TestTimeoutException:
    """Test TimeoutException."""
    
    def test_timeout_exception_initialization(self):
        """Test timeout exception initialization."""
        exc = TimeoutException("Operation timed out", 300)
        
        assert str(exc) == "Operation timed out"
        assert exc.message == "Operation timed out"
        assert exc.timeout_seconds == 300
        assert isinstance(exc, SolutionCreatorException)
    
    def test_timeout_exception_with_details(self):
        """Test timeout exception with details."""
        details = {"operation": "AI model call", "phase": "planning"}
        exc = TimeoutException("Timeout occurred", 600, details=details)
        
        assert exc.timeout_seconds == 600
        assert exc.details == details


class TestGitException:
    """Test GitException."""
    
    def test_git_exception_initialization(self):
        """Test git exception initialization."""
        exc = GitException("Git operation failed")
        
        assert str(exc) == "Git operation failed"
        assert exc.message == "Git operation failed"
        assert isinstance(exc, SolutionCreatorException)
    
    def test_git_exception_with_details(self):
        """Test git exception with details."""
        details = {"command": "git init", "exit_code": 1, "stderr": "Permission denied"}
        exc = GitException("Git init failed", details=details)
        
        assert exc.details == details


class TestFileSystemException:
    """Test FileSystemException."""
    
    def test_filesystem_exception_initialization(self):
        """Test filesystem exception initialization."""
        exc = FileSystemException("File operation failed", "/path/to/file.py")
        
        assert str(exc) == "File operation failed"
        assert exc.message == "File operation failed"
        assert exc.file_path == "/path/to/file.py"
        assert isinstance(exc, SolutionCreatorException)
    
    def test_filesystem_exception_with_details(self):
        """Test filesystem exception with details."""
        details = {"operation": "write", "permissions": "644", "size": 1024}
        exc = FileSystemException("Write failed", "/tmp/test.py", details=details)
        
        assert exc.file_path == "/tmp/test.py"
        assert exc.details == details


class TestCodeGenerationException:
    """Test CodeGenerationException."""
    
    def test_code_generation_exception_initialization(self):
        """Test code generation exception initialization."""
        exc = CodeGenerationException("Code generation failed", "generate_class")
        
        assert str(exc) == "Code generation failed"
        assert exc.message == "Code generation failed"
        assert exc.generation_step == "generate_class"
        assert isinstance(exc, SolutionCreatorException)
    
    def test_code_generation_exception_with_details(self):
        """Test code generation exception with details."""
        details = {"class_name": "BinarySearch", "method_count": 3, "ai_model": "gpt-4"}
        exc = CodeGenerationException("Class generation failed", "generate_class", details=details)
        
        assert exc.generation_step == "generate_class"
        assert exc.details == details


class TestExceptionHierarchy:
    """Test exception hierarchy and inheritance."""
    
    def test_all_exceptions_inherit_from_base(self):
        """Test that all custom exceptions inherit from SolutionCreatorException."""
        exceptions = [
            WorkspaceException("test"),
            CompilationException("test", []),
            TestExecutionException("test", []),
            LanguageHandlerException("test", "PYTHON"),
            MaxIterationsExceededException("test", 5),
            TimeoutException("test", 300),
            GitException("test"),
            FileSystemException("test", "/path"),
            CodeGenerationException("test", "step")
        ]
        
        for exc in exceptions:
            assert isinstance(exc, SolutionCreatorException)
            assert isinstance(exc, Exception)
    
    def test_exception_details_default_to_empty_dict(self):
        """Test that exception details default to empty dict when not provided."""
        exceptions = [
            SolutionCreatorException("test"),
            WorkspaceException("test"),
            GitException("test")
        ]
        
        for exc in exceptions:
            assert exc.details == {}
    
    def test_exception_message_attribute(self):
        """Test that all exceptions have message attribute."""
        test_message = "Test error message"
        exceptions = [
            SolutionCreatorException(test_message),
            WorkspaceException(test_message),
            CompilationException(test_message, []),
            TestExecutionException(test_message, []),
            LanguageHandlerException(test_message, "PYTHON"),
            MaxIterationsExceededException(test_message, 5),
            TimeoutException(test_message, 300),
            GitException(test_message),
            FileSystemException(test_message, "/path"),
            CodeGenerationException(test_message, "step")
        ]
        
        for exc in exceptions:
            assert exc.message == test_message
            assert str(exc) == test_message 
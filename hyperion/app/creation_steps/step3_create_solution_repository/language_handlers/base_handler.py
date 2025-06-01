"""Base language handler for solution repository creation."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

from ..models import SolutionCreationContext, FileStructure, TestExecutionResult
from ..exceptions import LanguageHandlerException

logger = logging.getLogger(__name__)


class BaseLanguageHandler(ABC):
    """Abstract base class for language-specific handlers."""

    def __init__(self, language: str) -> None:
        """
        Args:
            language: Programming language name
        """
        self.language = language
        self.logger = logging.getLogger(f"{__name__}.{language}")

    @abstractmethod
    def create_project_structure(self, context: SolutionCreationContext) -> FileStructure:
        """Create the project structure for this language.
        
        Args:
            context: The solution creation context
            
        Returns:
            FileStructure with directories and files to create
        """
        pass

    @abstractmethod
    def generate_build_file(self, context: SolutionCreationContext) -> str:
        """Generate the build configuration file.
        
        Args:
            context: The solution creation context
            
        Returns:
            Build file content as string
        """
        pass

    @abstractmethod
    def generate_class_header(self, class_name: str, context: SolutionCreationContext) -> str:
        """Generate a class header with proper syntax.
        
        Args:
            class_name: Name of the class
            context: The solution creation context
            
        Returns:
            Class header code as string
        """
        pass

    @abstractmethod
    def generate_function_header(self, function_name: str, parameters: List[Dict[str, str]], 
                               return_type: str, context: SolutionCreationContext) -> str:
        """Generate a function header with proper syntax.
        
        Args:
            function_name: Name of the function
            parameters: List of parameter dictionaries with 'name' and 'type'
            return_type: Return type of the function
            context: The solution creation context
            
        Returns:
            Function header code as string
        """
        pass

    @abstractmethod
    def generate_test_class(self, class_name: str, context: SolutionCreationContext) -> str:
        """Generate a test class for the given class.
        
        Args:
            class_name: Name of the class to test
            context: The solution creation context
            
        Returns:
            Test class code as string
        """
        pass

    @abstractmethod
    def compile_solution(self, context: SolutionCreationContext) -> TestExecutionResult:
        """Compile the solution code.
        
        Args:
            context: The solution creation context
            
        Returns:
            Compilation result
        """
        pass

    @abstractmethod
    def run_tests(self, context: SolutionCreationContext) -> TestExecutionResult:
        """Run tests for the solution.
        
        Args:
            context: The solution creation context
            
        Returns:
            Test execution result
        """
        pass

    @abstractmethod
    def parse_compilation_errors(self, output: str) -> List[str]:
        """Parse compilation errors from compiler output.
        
        Args:
            output: Compiler output
            
        Returns:
            List of parsed error messages
        """
        pass

    @abstractmethod
    def parse_test_failures(self, output: str) -> List[str]:
        """Parse test failures from test runner output.
        
        Args:
            output: Test runner output
            
        Returns:
            List of parsed test failure messages
        """
        pass

    @abstractmethod
    def fix_syntax_error(self, error: str, context: SolutionCreationContext) -> str:
        """Generate a fix for a syntax error.
        
        Args:
            error: Syntax error description
            context: The solution creation context
            
        Returns:
            Fix description or code change
        """
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        """Get the primary file extension for this language.
        
        Returns:
            File extension (e.g., '.java', '.py', '.js')
        """
        pass

    @abstractmethod
    def get_test_framework(self) -> str:
        """Get the default test framework for this language.
        
        Returns:
            Test framework name
        """
        pass

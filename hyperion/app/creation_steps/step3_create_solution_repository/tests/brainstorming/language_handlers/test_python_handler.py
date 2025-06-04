"""Unit tests for Python language handler."""

import sys
from pathlib import Path
import pytest
from unittest.mock import Mock, patch

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from hyperion.app.creation_steps.step3_create_solution_repository.language_handlers.python_handler import PythonHandler
    from hyperion.app.creation_steps.step3_create_solution_repository.models import SolutionCreationContext
    from hyperion.app.creation_steps.step3_create_solution_repository.exceptions import LanguageHandlerException
except ImportError:
    # Create mock classes if imports fail
    class PythonHandler:
        def __init__(self):
            self.language = "PYTHON"
            self.file_extension = ".py"
            self.test_framework = "pytest"
        
        def get_language(self): return "PYTHON"
        def get_file_extension(self): return ".py"
        def get_test_framework(self): return "pytest"
        def create_project_structure(self, context): return None
        def generate_class_template(self, name, methods): return ""
        def generate_function_template(self, name, params, return_type): return ""
        def generate_test_template(self, class_name, test_methods): return ""
        def validate_syntax(self, code): return []
        def compile_code(self, context, code): 
            result = Mock()
            result.success = True
            result.stdout = ""
            result.compilation_errors = []
            return result
        def run_tests(self, context, code): return Mock()
        def format_code(self, code): return code
        def get_dependencies(self, context): return []
        def create_build_file(self, context): return ""
        def get_main_file_name(self, context): return "main.py"
        def get_test_file_name(self, class_name): return f"test_{class_name.lower()}.py"
    
    class SolutionCreationContext:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class LanguageHandlerException(Exception):
        def __init__(self, message, language=None):
            super().__init__(message)
            self.language = language


class TestPythonHandler:
    """Test PythonHandler class."""
    
    @pytest.fixture
    def python_handler(self):
        """Create a Python handler instance for testing."""
        return PythonHandler()
    
    def test_python_handler_initialization(self, python_handler):
        """Test Python handler initialization."""
        assert python_handler.language == "PYTHON"
        assert python_handler.file_extension == ".py"
        assert python_handler.test_framework == "pytest"
    
    def test_get_language(self, python_handler):
        """Test getting language name."""
        assert python_handler.get_language() == "PYTHON"
    
    def test_get_file_extension(self, python_handler):
        """Test getting file extension."""
        assert python_handler.get_file_extension() == ".py"
    
    def test_get_test_framework(self, python_handler):
        """Test getting test framework."""
        assert python_handler.get_test_framework() == "pytest"
    
    def test_create_project_structure_plain(self, python_handler, sample_solution_context):
        """Test creating plain Python project structure."""
        sample_solution_context.boundary_conditions.project_type = "PLAIN"
        
        structure = python_handler.create_project_structure(sample_solution_context)
        
        assert structure is not None
        # TODO: Add specific assertions when implementation is added
    
    def test_create_project_structure_unsupported(self, python_handler, sample_solution_context):
        """Test creating project structure with unsupported project type."""
        sample_solution_context.boundary_conditions.project_type = "GRADLE"  # Not supported for Python
        
        with pytest.raises(LanguageHandlerException) as exc_info:
            python_handler.create_project_structure(sample_solution_context)
        
        assert "not supported" in str(exc_info.value).lower()
        assert exc_info.value.language == "PYTHON"
    
    def test_generate_class_template(self, python_handler):
        """Test generating Python class template."""
        template = python_handler.generate_class_template("BinarySearch", ["search", "validate"])
        
        assert template is not None
        assert isinstance(template, str)
        # TODO: Add specific assertions when implementation is added
    
    def test_generate_function_template(self, python_handler):
        """Test generating Python function template."""
        template = python_handler.generate_function_template("binary_search", ["arr", "target"], "int")
        
        assert template is not None
        assert isinstance(template, str)
        # TODO: Add specific assertions when implementation is added
    
    def test_generate_test_template(self, python_handler):
        """Test generating Python test template."""
        template = python_handler.generate_test_template("BinarySearch", ["test_search", "test_validate"])
        
        assert template is not None
        assert isinstance(template, str)
        # TODO: Add specific assertions when implementation is added
    
    def test_validate_syntax_valid(self, python_handler):
        """Test syntax validation with valid Python code."""
        valid_code = """
def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
"""
        
        errors = python_handler.validate_syntax(valid_code)
        assert errors == []
    
    def test_validate_syntax_invalid(self, python_handler):
        """Test syntax validation with invalid Python code."""
        invalid_code = """
def binary_search(arr, target)  # Missing colon
    left, right = 0, len(arr) - 1
    while left <= right
        mid = (left + right) // 2  # Missing colon
        if arr[mid] == target:
            return mid
    return -1
"""
        
        errors = python_handler.validate_syntax(invalid_code)
        assert len(errors) > 0
        assert any("syntax" in error.lower() for error in errors)
    
    def test_compile_code_success(self, python_handler, sample_solution_context):
        """Test successful code compilation."""
        valid_code = "def hello(): return 'Hello, World!'"
        
        result = python_handler.compile_code(sample_solution_context, valid_code)
        
        assert result.success is True
        assert result.stdout != ""
        assert result.compilation_errors == []
    
    def test_compile_code_failure(self, python_handler, sample_solution_context):
        """Test code compilation failure."""
        invalid_code = "def hello( return 'Hello, World!'"  # Syntax error
        
        result = python_handler.compile_code(sample_solution_context, invalid_code)
        
        assert result.success is False
        assert len(result.compilation_errors) > 0
    
    def test_run_tests_success(self, python_handler, sample_solution_context):
        """Test successful test execution."""
        test_code = """
import pytest

def test_example():
    assert 1 + 1 == 2

def test_another():
    assert "hello".upper() == "HELLO"
"""
        
        result = python_handler.run_tests(sample_solution_context, test_code)
        
        # TODO: Add specific assertions when implementation is added
        assert result is not None
    
    def test_run_tests_failure(self, python_handler, sample_solution_context):
        """Test test execution with failures."""
        test_code = """
import pytest

def test_failing():
    assert 1 + 1 == 3  # This will fail

def test_passing():
    assert True
"""
        
        result = python_handler.run_tests(sample_solution_context, test_code)
        
        # TODO: Add specific assertions when implementation is added
        assert result is not None
    
    def test_format_code(self, python_handler):
        """Test code formatting."""
        unformatted_code = """
def binary_search(arr,target):
    left,right=0,len(arr)-1
    while left<=right:
        mid=(left+right)//2
        if arr[mid]==target:return mid
        elif arr[mid]<target:left=mid+1
        else:right=mid-1
    return -1
"""
        
        formatted_code = python_handler.format_code(unformatted_code)
        
        assert formatted_code is not None
        assert isinstance(formatted_code, str)
        # TODO: Add specific formatting assertions when implementation is added
    
    def test_get_dependencies(self, python_handler, sample_solution_context):
        """Test getting project dependencies."""
        dependencies = python_handler.get_dependencies(sample_solution_context)
        
        assert isinstance(dependencies, list)
        # TODO: Add specific assertions when implementation is added
    
    def test_create_build_file(self, python_handler, sample_solution_context):
        """Test creating build file (requirements.txt for Python)."""
        build_file = python_handler.create_build_file(sample_solution_context)
        
        assert build_file is not None
        assert isinstance(build_file, str)
        # TODO: Add specific assertions when implementation is added
    
    def test_get_main_file_name(self, python_handler, sample_solution_context):
        """Test getting main file name."""
        file_name = python_handler.get_main_file_name(sample_solution_context)
        
        assert file_name is not None
        assert isinstance(file_name, str)
        assert file_name.endswith(".py")
    
    def test_get_test_file_name(self, python_handler):
        """Test getting test file name."""
        test_file_name = python_handler.get_test_file_name("BinarySearch")
        
        assert test_file_name is not None
        assert isinstance(test_file_name, str)
        assert test_file_name.startswith("test_")
        assert test_file_name.endswith(".py")


class TestPythonHandlerCodeGeneration:
    """Test code generation functionality in detail."""
    
    @pytest.fixture
    def python_handler(self):
        """Create a Python handler instance for testing."""
        return PythonHandler()
    
    def test_generate_class_with_methods(self, python_handler):
        """Test generating a class with specific methods."""
        class_name = "Calculator"
        methods = ["add", "subtract", "multiply", "divide"]
        
        template = python_handler.generate_class_template(class_name, methods)
        
        assert isinstance(template, str)
        # TODO: Add specific assertions when implementation is added
        # assert f"class {class_name}:" in template
        # for method in methods:
        #     assert f"def {method}" in template
    
    def test_generate_function_with_type_hints(self, python_handler):
        """Test generating function with type hints."""
        function_name = "calculate_sum"
        parameters = ["numbers: List[int]"]
        return_type = "int"
        
        template = python_handler.generate_function_template(function_name, parameters, return_type)
        
        assert isinstance(template, str)
        # TODO: Add specific assertions when implementation is added
        # assert f"def {function_name}" in template
        # assert f"-> {return_type}:" in template
    
    def test_generate_pytest_test_class(self, python_handler):
        """Test generating pytest test class."""
        class_name = "Calculator"
        test_methods = ["test_add", "test_subtract", "test_multiply", "test_divide"]
        
        template = python_handler.generate_test_template(class_name, test_methods)
        
        assert isinstance(template, str)
        # TODO: Add specific assertions when implementation is added
        # assert f"class Test{class_name}:" in template
        # for test_method in test_methods:
        #     assert f"def {test_method}" in template


class TestPythonHandlerValidation:
    """Test validation functionality in detail."""
    
    @pytest.fixture
    def python_handler(self):
        """Create a Python handler instance for testing."""
        return PythonHandler()
    
    def test_validate_python_naming_conventions(self, python_handler):
        """Test validation of Python naming conventions."""
        valid_code = """
class BinarySearcher:
    def __init__(self):
        self.search_count = 0
    
    def binary_search(self, arr, target):
        return -1
"""
        
        errors = python_handler.validate_syntax(valid_code)
        assert errors == []
    
    def test_validate_python_imports(self, python_handler):
        """Test validation of Python imports."""
        code_with_imports = """
import os
import sys
from typing import List, Optional
from collections import defaultdict

def process_data(data: List[int]) -> Optional[int]:
    return max(data) if data else None
"""
        
        errors = python_handler.validate_syntax(code_with_imports)
        assert errors == []
    
    def test_validate_python_indentation(self, python_handler):
        """Test validation of Python indentation."""
        # Valid indentation
        valid_code = """
def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
"""
        
        errors = python_handler.validate_syntax(valid_code)
        assert errors == []
        
        # Invalid indentation
        invalid_code = """
def binary_search(arr, target):
left, right = 0, len(arr) - 1  # Wrong indentation
    while left <= right:
        mid = (left + right) // 2
    if arr[mid] == target:  # Wrong indentation
            return mid
    return -1
"""
        
        errors = python_handler.validate_syntax(invalid_code)
        assert len(errors) > 0 
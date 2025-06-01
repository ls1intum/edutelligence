"""Pytest configuration and shared fixtures for Step 3 tests."""

import sys
import os
from pathlib import Path
import pytest
from unittest.mock import Mock, AsyncMock
from typing import Dict, Any

# Add the project root to Python path so we can import modules
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from langchain_core.language_models.chat_models import BaseLanguageModel
except ImportError:
    # Mock BaseLanguageModel if langchain is not available
    class BaseLanguageModel:
        pass

try:
    from hyperion.app.grpc.models import BoundaryConditions, ProblemStatement, Repository, RepositoryFile
except ImportError:
    # Create mock classes if the actual models are not available
    class BoundaryConditions:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class ProblemStatement:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class Repository:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class RepositoryFile:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

try:
    from hyperion.app.creation_steps.step3_create_solution_repository.models import (
        SolutionCreationContext, 
        SolutionCreationPhase, 
        SolutionCreationStep,
        SolutionRepositoryCreatorRequest,
        SolutionRepositoryCreatorResponse,
        SolutionPlan,
        FileStructure
    )
except ImportError:
    # Create mock classes if the actual models are not available
    from enum import Enum
    
    class SolutionCreationPhase(Enum):
        PLANNING = "planning"
        TESTING = "testing"
        VALIDATION = "validation"
    
    class SolutionCreationStep(Enum):
        GENERATE_PLAN = "generate_plan"
        DEFINE_STRUCTURE = "define_structure"
        GENERATE_HEADERS = "generate_headers"
        GENERATE_LOGIC = "generate_logic"
        CREATE_TEST_INFRA = "create_test_infra"
        WRITE_UNIT_TESTS = "write_unit_tests"
        WRITE_E2E_TESTS = "write_e2e_tests"
        EXECUTE_TESTS = "execute_tests"
        EVALUATE_OUTPUT = "evaluate_output"
        ITERATIVE_FIX = "iterative_fix"
    
    class SolutionCreationContext:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class SolutionRepositoryCreatorRequest:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class SolutionRepositoryCreatorResponse:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class SolutionPlan:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class FileStructure:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


@pytest.fixture
def mock_model():
    """Mock AI language model for testing."""
    model = Mock(spec=BaseLanguageModel)
    model.ainvoke = AsyncMock()
    model.invoke = Mock()
    return model


@pytest.fixture
def sample_boundary_conditions():
    """Sample boundary conditions for testing."""
    return BoundaryConditions(
        language="English",
        technical_environment="Development",
        project_type="MAVEN",
        programming_language="PYTHON",
        difficulty="Medium",
        points=100,
        bonus_points=20,
        constraints=["No external libraries", "Time limit: 2 hours"]
    )


@pytest.fixture
def sample_problem_statement():
    """Sample problem statement for testing."""
    return ProblemStatement(
        title="Binary Search Implementation",
        short_title="Binary Search",
        description="Implement a binary search algorithm that finds the index of a target value in a sorted array."
    )


@pytest.fixture
def sample_solution_context(mock_model, sample_boundary_conditions, sample_problem_statement):
    """Sample solution creation context for testing."""
    return SolutionCreationContext(
        boundary_conditions=sample_boundary_conditions,
        problem_statement=sample_problem_statement,
        workspace_path="/tmp/test_workspace",
        current_phase=SolutionCreationPhase.PLANNING,
        current_step=SolutionCreationStep.GENERATE_PLAN,
        model=mock_model
    )


@pytest.fixture
def sample_solution_plan():
    """Sample solution plan for testing."""
    return SolutionPlan(
        architecture_description="Simple binary search implementation with helper methods",
        required_classes=["BinarySearch", "SearchResult"],
        required_functions=["binary_search", "validate_input", "find_middle"],
        algorithms=["Binary Search", "Input Validation"],
        design_patterns=["Strategy Pattern"]
    )


@pytest.fixture
def sample_file_structure():
    """Sample file structure for testing."""
    return FileStructure(
        directories=["src", "src/main", "src/test", "target"],
        files=["src/main/BinarySearch.py", "src/test/test_binary_search.py"],
        build_files=["pom.xml", "requirements.txt"]
    )


@pytest.fixture
def sample_repository():
    """Sample repository for testing."""
    return Repository(
        name="binary-search-solution",
        files=[
            RepositoryFile(
                path="src/main/BinarySearch.py",
                content="def binary_search(arr, target):\n    # Implementation here\n    pass"
            ),
            RepositoryFile(
                path="src/test/test_binary_search.py",
                content="import unittest\n\nclass TestBinarySearch(unittest.TestCase):\n    pass"
            )
        ]
    )


@pytest.fixture
def sample_request(sample_boundary_conditions, sample_problem_statement):
    """Sample solution repository creator request."""
    return SolutionRepositoryCreatorRequest(
        boundary_conditions=sample_boundary_conditions,
        problem_statement=sample_problem_statement
    )


@pytest.fixture
def sample_response(sample_boundary_conditions, sample_problem_statement, sample_repository):
    """Sample solution repository creator response."""
    return SolutionRepositoryCreatorResponse(
        boundary_conditions=sample_boundary_conditions,
        problem_statement=sample_problem_statement,
        solution_repository=sample_repository,
        success=True,
        error_message=None,
        metadata={"test": "data"}
    )


@pytest.fixture
def mock_workspace_manager():
    """Mock workspace manager for testing."""
    manager = Mock()
    manager.create_workspace = Mock(return_value="/tmp/test_workspace")
    manager.cleanup_workspace = Mock()
    return manager


@pytest.fixture
def mock_language_registry():
    """Mock language registry for testing."""
    registry = Mock()
    registry.is_supported = Mock(return_value=True)
    registry.get_supported_languages = Mock(return_value=["PYTHON"])
    registry.get_handler_info = Mock(return_value={"name": "python", "version": "3.9"})
    return registry 
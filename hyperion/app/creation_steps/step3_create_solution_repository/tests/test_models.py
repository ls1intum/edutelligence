"""Unit tests for Step 3 models."""

import pytest
from unittest.mock import Mock
from pydantic import ValidationError

from app.grpc import hyperion_pb2
from app.grpc.models import BoundaryConditions, ProblemStatement, Repository
from ..models import (
    SolutionCreationContext,
    SolutionCreationPhase,
    SolutionCreationStep,
    SolutionPlan,
    FileStructure,
    TestExecutionResult,
    FixAttempt,
    SolutionRepositoryCreatorRequest,
    SolutionRepositoryCreatorResponse
)


class TestSolutionCreationPhase:
    """Test SolutionCreationPhase enum."""
    
    def test_phase_values(self):
        """Test that all phase values are correct."""
        assert SolutionCreationPhase.PLANNING == "planning"
        assert SolutionCreationPhase.TESTING == "testing"
        assert SolutionCreationPhase.VALIDATION == "validation"
    
    def test_phase_enum_membership(self):
        """Test phase enum membership."""
        assert "planning" in SolutionCreationPhase
        assert "testing" in SolutionCreationPhase
        assert "validation" in SolutionCreationPhase
        assert "invalid_phase" not in SolutionCreationPhase


class TestSolutionCreationStep:
    """Test SolutionCreationStep enum."""
    
    def test_step_values(self):
        """Test that all step values are correct."""
        assert SolutionCreationStep.GENERATE_PLAN == "generate_plan"
        assert SolutionCreationStep.DEFINE_STRUCTURE == "define_structure"
        assert SolutionCreationStep.GENERATE_HEADERS == "generate_headers"
        assert SolutionCreationStep.GENERATE_LOGIC == "generate_logic"
        assert SolutionCreationStep.CREATE_TEST_INFRA == "create_test_infra"
        assert SolutionCreationStep.WRITE_UNIT_TESTS == "write_unit_tests"
        assert SolutionCreationStep.WRITE_E2E_TESTS == "write_e2e_tests"
        assert SolutionCreationStep.EXECUTE_TESTS == "execute_tests"
        assert SolutionCreationStep.EVALUATE_OUTPUT == "evaluate_output"
        assert SolutionCreationStep.ITERATIVE_FIX == "iterative_fix"


class TestSolutionPlan:
    """Test SolutionPlan model."""
    
    def test_solution_plan_creation(self, sample_solution_plan):
        """Test creating a solution plan."""
        assert sample_solution_plan.architecture_description == "Simple binary search implementation with helper methods"
        assert "BinarySearch" in sample_solution_plan.required_classes
        assert "binary_search" in sample_solution_plan.required_functions
        assert "Binary Search" in sample_solution_plan.algorithms
        assert "Strategy Pattern" in sample_solution_plan.design_patterns
    
    def test_solution_plan_defaults(self):
        """Test solution plan with default values."""
        plan = SolutionPlan(architecture_description="Test architecture")
        assert plan.required_classes == []
        assert plan.required_functions == []
        assert plan.algorithms == []
        assert plan.design_patterns == []
    
    def test_solution_plan_validation(self):
        """Test solution plan validation."""
        with pytest.raises(ValidationError):
            SolutionPlan()  # Missing required architecture_description


class TestFileStructure:
    """Test FileStructure model."""
    
    def test_file_structure_creation(self, sample_file_structure):
        """Test creating a file structure."""
        assert "src" in sample_file_structure.directories
        assert "src/main/BinarySearch.py" in sample_file_structure.files
        assert "pom.xml" in sample_file_structure.build_files
    
    def test_file_structure_defaults(self):
        """Test file structure with default values."""
        structure = FileStructure()
        assert structure.directories == []
        assert structure.files == []
        assert structure.build_files == []


class TestTestExecutionResult:
    """Test TestExecutionResult model."""
    
    def test_test_execution_result_success(self):
        """Test successful test execution result."""
        result = TestExecutionResult(
            success=True,
            stdout="All tests passed",
            stderr="",
            test_results={"passed": 5, "failed": 0}
        )
        assert result.success is True
        assert result.stdout == "All tests passed"
        assert result.compilation_errors == []
        assert result.runtime_errors == []
    
    def test_test_execution_result_failure(self):
        """Test failed test execution result."""
        result = TestExecutionResult(
            success=False,
            stdout="",
            stderr="Test failed",
            compilation_errors=["Syntax error on line 10"],
            runtime_errors=["IndexError: list index out of range"]
        )
        assert result.success is False
        assert result.stderr == "Test failed"
        assert len(result.compilation_errors) == 1
        assert len(result.runtime_errors) == 1


class TestFixAttempt:
    """Test FixAttempt model."""
    
    def test_fix_attempt_creation(self):
        """Test creating a fix attempt."""
        fix = FixAttempt(
            iteration=1,
            issue_description="Syntax error in binary_search function",
            fix_description="Fixed missing colon in if statement",
            files_modified=["src/main/BinarySearch.py"],
            success=True
        )
        assert fix.iteration == 1
        assert "Syntax error" in fix.issue_description
        assert fix.success is True
        assert "src/main/BinarySearch.py" in fix.files_modified


class TestSolutionCreationContext:
    """Test SolutionCreationContext model."""
    
    def test_context_creation(self, sample_solution_context):
        """Test creating a solution creation context."""
        assert sample_solution_context.current_phase == SolutionCreationPhase.PLANNING
        assert sample_solution_context.current_step == SolutionCreationStep.GENERATE_PLAN
        assert sample_solution_context.workspace_path == "/tmp/test_workspace"
        assert sample_solution_context.model is not None
    
    def test_context_with_solution_plan(self, sample_solution_context, sample_solution_plan):
        """Test context with solution plan."""
        sample_solution_context.solution_plan = sample_solution_plan
        assert sample_solution_context.solution_plan is not None
        assert sample_solution_context.solution_plan.architecture_description == "Simple binary search implementation with helper methods"
    
    def test_context_model_exclusion(self, sample_solution_context):
        """Test that model is excluded from serialization."""
        # The model should be excluded when converting to dict
        context_dict = sample_solution_context.dict()
        assert "model" not in context_dict
    
    def test_context_defaults(self, mock_model, sample_boundary_conditions, sample_problem_statement):
        """Test context with default values."""
        context = SolutionCreationContext(
            boundary_conditions=sample_boundary_conditions,
            problem_statement=sample_problem_statement,
            workspace_path="/tmp/test",
            current_phase=SolutionCreationPhase.PLANNING,
            current_step=SolutionCreationStep.GENERATE_PLAN,
            model=mock_model
        )
        assert context.solution_plan is None
        assert context.file_structure is None
        assert context.solution_repository is None
        assert context.test_results == []
        assert context.fix_attempts == []
        assert context.metadata == {}


class TestSolutionRepositoryCreatorRequest:
    """Test SolutionRepositoryCreatorRequest model."""
    
    def test_request_creation(self, sample_request):
        """Test creating a request."""
        assert sample_request.boundary_conditions.programming_language == "PYTHON"
        assert sample_request.problem_statement.title == "Binary Search Implementation"
    
    def test_request_to_grpc(self, sample_request):
        """Test converting request to gRPC."""
        grpc_request = sample_request.to_grpc()
        assert isinstance(grpc_request, hyperion_pb2.SolutionRepositoryCreatorRequest)
        assert grpc_request.boundary_conditions.programming_language == "PYTHON"
        assert grpc_request.problem_statement.title == "Binary Search Implementation"
    
    def test_request_from_grpc(self, sample_boundary_conditions, sample_problem_statement):
        """Test creating request from gRPC."""
        grpc_request = hyperion_pb2.SolutionRepositoryCreatorRequest(
            boundary_conditions=sample_boundary_conditions.to_grpc(),
            problem_statement=sample_problem_statement.to_grpc()
        )
        request = SolutionRepositoryCreatorRequest.from_grpc(grpc_request)
        assert request.boundary_conditions.programming_language == "PYTHON"
        assert request.problem_statement.title == "Binary Search Implementation"


class TestSolutionRepositoryCreatorResponse:
    """Test SolutionRepositoryCreatorResponse model."""
    
    def test_response_creation(self, sample_response):
        """Test creating a response."""
        assert sample_response.success is True
        assert sample_response.error_message is None
        assert sample_response.solution_repository.name == "binary-search-solution"
        assert sample_response.metadata == {"test": "data"}
    
    def test_response_failure(self, sample_boundary_conditions, sample_problem_statement, sample_repository):
        """Test creating a failure response."""
        response = SolutionRepositoryCreatorResponse(
            boundary_conditions=sample_boundary_conditions,
            problem_statement=sample_problem_statement,
            solution_repository=sample_repository,
            success=False,
            error_message="Generation failed due to timeout"
        )
        assert response.success is False
        assert response.error_message == "Generation failed due to timeout"
    
    def test_response_to_grpc(self, sample_response):
        """Test converting response to gRPC."""
        grpc_response = sample_response.to_grpc()
        assert isinstance(grpc_response, hyperion_pb2.SolutionRepositoryCreatorResponse)
        assert grpc_response.success is True
        assert grpc_response.solution_repository.name == "binary-search-solution"
    
    def test_response_from_grpc(self, sample_boundary_conditions, sample_problem_statement, sample_repository):
        """Test creating response from gRPC."""
        grpc_response = hyperion_pb2.SolutionRepositoryCreatorResponse(
            boundary_conditions=sample_boundary_conditions.to_grpc(),
            problem_statement=sample_problem_statement.to_grpc(),
            solution_repository=sample_repository.to_grpc(),
            success=True,
            error_message=""
        )
        response = SolutionRepositoryCreatorResponse.from_grpc(grpc_response)
        assert response.success is True
        assert response.error_message is None
        assert response.solution_repository.name == "binary-search-solution" 
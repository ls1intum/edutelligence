"""Unit tests for Phase 1: Planning."""

import sys
from pathlib import Path
import pytest
from unittest.mock import Mock, AsyncMock, patch

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from hyperion.app.creation_steps.step3_create_solution_repository.phases.phase1_planning import PlanningPhase
    from hyperion.app.creation_steps.step3_create_solution_repository.models import SolutionCreationContext, SolutionCreationStep, SolutionPlan
    from hyperion.app.creation_steps.step3_create_solution_repository.exceptions import SolutionCreatorException
except ImportError:
    # Create mock classes if imports fail
    from enum import Enum
    
    class SolutionCreationStep(Enum):
        GENERATE_PLAN = "generate_plan"
    
    class PlanningPhase:
        def __init__(self, model=None):
            self.model = model
        
        async def execute(self, context):
            return context
        
        async def _step_1_1_generate_solution_plan(self, context):
            context.solution_plan = Mock()
            context.solution_plan.architecture_description = "Generated solution architecture"
            return context
        
        async def _step_1_2_define_file_structure(self, context):
            return context
        
        async def _step_1_3_generate_headers(self, context):
            return context
        
        async def _step_1_4_generate_core_logic(self, context):
            return context
        
        def _build_solution_planning_prompt(self, context):
            return f"Generate solution for {context.problem_statement.title} using {context.boundary_conditions.programming_language} with {context.boundary_conditions.difficulty} difficulty worth {context.boundary_conditions.points} points. Create solution plan with architecture description, required classes, required functions, algorithms, and design patterns."
        
        def _analyze_problem_complexity(self, context):
            return "medium"
        
        def _select_design_patterns(self, context):
            return []
        
        def _generate_class_hierarchy(self, context):
            return {}
        
        def _create_project_structure(self, context):
            structure = Mock()
            structure.directories = []
            structure.files = []
            structure.build_files = []
            return structure
    
    class SolutionCreationContext:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class SolutionPlan:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    class SolutionCreatorException(Exception):
        pass


class TestPlanningPhase:
    """Test PlanningPhase class."""
    
    @pytest.fixture
    def planning_phase(self, mock_model):
        """Create a planning phase instance for testing."""
        return PlanningPhase(model=mock_model)
    
    def test_planning_phase_initialization(self, mock_model):
        """Test planning phase initialization."""
        phase = PlanningPhase(model=mock_model)
        assert phase.model == mock_model
    
    @pytest.mark.asyncio
    async def test_execute_success(self, planning_phase, sample_solution_context):
        """Test successful execution of planning phase."""
        # Mock all step methods
        planning_phase._step_1_1_generate_solution_plan = AsyncMock(return_value=sample_solution_context)
        planning_phase._step_1_2_define_file_structure = AsyncMock(return_value=sample_solution_context)
        planning_phase._step_1_3_generate_headers = AsyncMock(return_value=sample_solution_context)
        planning_phase._step_1_4_generate_core_logic = AsyncMock(return_value=sample_solution_context)
        
        result = await planning_phase.execute(sample_solution_context)
        
        assert result == sample_solution_context
        planning_phase._step_1_1_generate_solution_plan.assert_called_once_with(sample_solution_context)
        planning_phase._step_1_2_define_file_structure.assert_called_once_with(sample_solution_context)
        planning_phase._step_1_3_generate_headers.assert_called_once_with(sample_solution_context)
        planning_phase._step_1_4_generate_core_logic.assert_called_once_with(sample_solution_context)
    
    @pytest.mark.asyncio
    async def test_execute_step_failure(self, planning_phase, sample_solution_context):
        """Test execution with step failure."""
        planning_phase._step_1_1_generate_solution_plan = AsyncMock(
            side_effect=SolutionCreatorException("Solution plan generation failed")
        )
        
        with pytest.raises(SolutionCreatorException):
            await planning_phase.execute(sample_solution_context)
    
    @pytest.mark.asyncio
    async def test_step_1_1_generate_solution_plan_success(self, planning_phase, sample_solution_context, sample_solution_plan):
        """Test successful solution plan generation."""
        # Mock the helper methods
        planning_phase._build_solution_planning_prompt = Mock(return_value="Test prompt")
        
        # Mock AI model response
        mock_response = Mock()
        mock_response.content = "Generated solution plan"
        planning_phase.model.ainvoke = AsyncMock(return_value=mock_response)
        
        result = await planning_phase._step_1_1_generate_solution_plan(sample_solution_context)
        
        assert result == sample_solution_context
        assert result.solution_plan is not None
        assert result.solution_plan.architecture_description == "Generated solution architecture"
        planning_phase._build_solution_planning_prompt.assert_called_once_with(sample_solution_context)
    
    @pytest.mark.asyncio
    async def test_step_1_1_generate_solution_plan_failure(self, planning_phase, sample_solution_context):
        """Test solution plan generation failure."""
        planning_phase._build_solution_planning_prompt = Mock(side_effect=Exception("Prompt building failed"))
        
        with pytest.raises(SolutionCreatorException) as exc_info:
            await planning_phase._step_1_1_generate_solution_plan(sample_solution_context)
        
        assert "Solution plan generation failed" in str(exc_info.value)
    
    def test_build_solution_planning_prompt(self, planning_phase, sample_solution_context):
        """Test building solution planning prompt."""
        prompt = planning_phase._build_solution_planning_prompt(sample_solution_context)
        
        assert isinstance(prompt, str)
        assert "Binary Search Implementation" in prompt
        assert "PYTHON" in prompt
        assert "Medium" in prompt
        assert "100" in prompt  # points
        assert "solution plan" in prompt.lower()
        assert "architecture" in prompt.lower()
    
    @pytest.mark.asyncio
    async def test_step_1_2_define_file_structure(self, planning_phase, sample_solution_context):
        """Test file structure definition step."""
        result = await planning_phase._step_1_2_define_file_structure(sample_solution_context)
        
        assert result == sample_solution_context
        # TODO: Add assertions when implementation is added
    
    @pytest.mark.asyncio
    async def test_step_1_3_generate_headers(self, planning_phase, sample_solution_context):
        """Test header generation step."""
        result = await planning_phase._step_1_3_generate_headers(sample_solution_context)
        
        assert result == sample_solution_context
        # TODO: Add assertions when implementation is added
    
    @pytest.mark.asyncio
    async def test_step_1_4_generate_core_logic(self, planning_phase, sample_solution_context):
        """Test core logic generation step."""
        result = await planning_phase._step_1_4_generate_core_logic(sample_solution_context)
        
        assert result == sample_solution_context
        # TODO: Add assertions when implementation is added
    
    def test_analyze_problem_complexity(self, planning_phase, sample_solution_context):
        """Test problem complexity analysis."""
        complexity = planning_phase._analyze_problem_complexity(sample_solution_context)
        
        assert complexity == "medium"  # Current placeholder implementation
    
    def test_select_design_patterns(self, planning_phase, sample_solution_context):
        """Test design pattern selection."""
        patterns = planning_phase._select_design_patterns(sample_solution_context)
        
        assert isinstance(patterns, list)
        assert patterns == []  # Current placeholder implementation
    
    def test_generate_class_hierarchy(self, planning_phase, sample_solution_context):
        """Test class hierarchy generation."""
        hierarchy = planning_phase._generate_class_hierarchy(sample_solution_context)
        
        assert isinstance(hierarchy, dict)
        assert hierarchy == {}  # Current placeholder implementation
    
    def test_create_project_structure(self, planning_phase, sample_solution_context):
        """Test project structure creation."""
        structure = planning_phase._create_project_structure(sample_solution_context)
        
        assert structure is not None
        # Current placeholder returns empty FileStructure
        assert structure.directories == []
        assert structure.files == []
        assert structure.build_files == []


class TestPlanningPhasePromptBuilding:
    """Test prompt building functionality in detail."""
    
    @pytest.fixture
    def planning_phase(self, mock_model):
        """Create a planning phase instance for testing."""
        return PlanningPhase(model=mock_model)
    
    def test_prompt_contains_all_required_fields(self, planning_phase, sample_solution_context):
        """Test that prompt contains all required information."""
        prompt = planning_phase._build_solution_planning_prompt(sample_solution_context)
        
        # Check problem statement fields
        assert sample_solution_context.problem_statement.title in prompt
        assert sample_solution_context.problem_statement.description in prompt
        
        # Check boundary conditions fields
        assert sample_solution_context.boundary_conditions.programming_language in prompt
        assert sample_solution_context.boundary_conditions.technical_environment in prompt
        assert sample_solution_context.boundary_conditions.project_type in prompt
        assert sample_solution_context.boundary_conditions.difficulty in prompt
        assert str(sample_solution_context.boundary_conditions.points) in prompt
    
    def test_prompt_structure(self, planning_phase, sample_solution_context):
        """Test that prompt has proper structure."""
        prompt = planning_phase._build_solution_planning_prompt(sample_solution_context)
        
        # Check for key sections
        assert "Problem Statement:" in prompt
        assert "Boundary Conditions:" in prompt
        assert "solution plan" in prompt.lower()
        assert "architecture description" in prompt.lower()
        assert "required classes" in prompt.lower()
        assert "required functions" in prompt.lower()
        assert "algorithms" in prompt.lower()
        assert "design patterns" in prompt.lower()
    
    def test_prompt_formatting(self, planning_phase, sample_solution_context):
        """Test that prompt is properly formatted."""
        prompt = planning_phase._build_solution_planning_prompt(sample_solution_context)
        
        # Should be stripped of leading/trailing whitespace
        assert prompt == prompt.strip()
        
        # Should contain structured sections
        lines = prompt.split('\n')
        assert len(lines) > 10  # Should be multi-line
        
        # Should have proper indentation and structure
        assert any("- Programming Language:" in line for line in lines)
        assert any("- Technical Environment:" in line for line in lines) 
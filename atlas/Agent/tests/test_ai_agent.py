import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os

# Add src directory to path for testing
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from ai_agent import AIAgent
from atlas_client import Competency
from artemis_client import CompetencyMapping


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    with patch('ai_agent.AgentConfig') as mock_config:
        mock_config.OPENAI_API_KEY = "test-key"
        mock_config.AZURE_API_VERSION = "2024-02-15-preview"  
        mock_config.AZURE_ENDPOINT = "https://test.openai.azure.com/"
        yield mock_config


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client."""
    with patch('ai_agent.AzureOpenAI') as mock_client:
        yield mock_client


@pytest.fixture
def agent(mock_config, mock_openai_client):
    """Create AIAgent for testing."""
    with patch('ai_agent.AtlasAPIClient'), patch('ai_agent.ArtemisAPIClient'):
        agent = AIAgent()
        agent.atlas_client = AsyncMock()
        agent.artemis_client = AsyncMock()
        return agent


class TestAIAgent:
    """Test suite for AIAgent."""

    def test_agent_initialization(self, mock_config, mock_openai_client):
        """Test agent initializes correctly."""
        with patch('ai_agent.AtlasAPIClient'), patch('ai_agent.ArtemisAPIClient'):
            agent = AIAgent()
            
            assert agent.model_name == "gpt-4o"
            assert agent.pending_confirmation is None
            assert len(agent.memory) == 1  # System prompt
            assert agent.memory[0]["role"] == "system"

    def test_system_prompt_content(self, agent):
        """Test system prompt contains required instructions."""
        system_prompt = agent._create_system_prompt()
        
        assert "Atlas competency management" in system_prompt
        assert "Artemis course management" in system_prompt
        assert "ask for confirmation" in system_prompt
        assert "get_competency_suggestions" in system_prompt

    @pytest.mark.asyncio
    async def test_handle_confirmation_accept(self, agent):
        """Test handling user acceptance of mapping."""
        # Set up pending confirmation
        agent.pending_confirmation = {
            'type': 'apply_competency_mapping',
            'data': {
                'competency_id': 'comp1',
                'exercise_id': 123,
                'course_id': '456'
            }
        }
        
        # Mock successful mapping application
        agent.artemis_client.apply_competency_mapping = MagicMock(return_value=True)
        
        response = await agent._handle_confirmation("yes")
        
        assert "Successfully applied competency mapping" in response
        assert agent.pending_confirmation is None
        agent.artemis_client.apply_competency_mapping.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_confirmation_reject(self, agent):
        """Test handling user rejection of mapping."""
        agent.pending_confirmation = {
            'type': 'apply_competency_mapping',
            'data': {'competency_id': 'comp1', 'exercise_id': 123, 'course_id': '456'}
        }
        
        response = await agent._handle_confirmation("no")
        
        assert "won't apply that mapping" in response
        assert agent.pending_confirmation is None

    @pytest.mark.asyncio
    async def test_get_competency_suggestions_success(self, agent):
        """Test successful competency suggestions."""
        # Mock competencies
        mock_competencies = [
            Competency(
                id="comp1",
                title="Sorting Algorithms", 
                description="Basic sorting algorithms",
                course_id="course1"
            )
        ]
        
        agent.atlas_client.suggest_competencies = AsyncMock(return_value=mock_competencies)
        agent.atlas_client.format_competencies_for_display = MagicMock(return_value="Formatted competencies")
        
        result = await agent._get_competency_suggestions("sorting", "course1")
        
        assert "Formatted competencies" in result
        assert "apply any of these competency mappings" in result
        agent.atlas_client.suggest_competencies.assert_called_once_with("sorting", "course1")

    @pytest.mark.asyncio
    async def test_get_competency_suggestions_empty(self, agent):
        """Test handling empty competency suggestions."""
        agent.atlas_client.suggest_competencies = AsyncMock(return_value=[])
        
        result = await agent._get_competency_suggestions("unknown", "course1")
        
        assert "No competencies found" in result

    @pytest.mark.asyncio
    async def test_get_competency_suggestions_error(self, agent):
        """Test handling error in competency suggestions."""
        agent.atlas_client.suggest_competencies = AsyncMock(
            side_effect=Exception("Atlas API error")
        )
        
        result = await agent._get_competency_suggestions("test", "course1")
        
        assert "Failed to get competency suggestions" in result

    def test_request_competency_mapping_confirmation(self, agent):
        """Test requesting confirmation for competency mapping."""
        response = agent.request_competency_mapping_confirmation("comp1", 123, 456)
        
        assert "Do you want to apply competency 'comp1' to exercise 123?" in response
        assert agent.pending_confirmation is not None
        assert agent.pending_confirmation['type'] == 'apply_competency_mapping'
        assert agent.pending_confirmation['data']['competency_id'] == "comp1"

    def test_reset_memory(self, agent):
        """Test memory reset functionality."""
        # Add some conversation history
        agent.memory.append({"role": "user", "content": "test"})
        agent.memory.append({"role": "assistant", "content": "response"})
        agent.pending_confirmation = {"type": "test"}
        
        agent.reset_memory()
        
        assert len(agent.memory) == 1  # Only system prompt should remain
        assert agent.memory[0]["role"] == "system"
        assert agent.pending_confirmation is None

    def test_function_definitions(self, agent):
        """Test function definitions are properly structured."""
        functions = agent._get_function_definitions()
        
        assert len(functions) == 3
        function_names = [f["name"] for f in functions]
        assert "get_competency_suggestions" in function_names
        assert "get_courses" in function_names
        assert "get_exercises" in function_names
        
        # Check competency suggestions function structure
        competency_func = next(f for f in functions if f["name"] == "get_competency_suggestions")
        assert "description" in competency_func["parameters"]["properties"]
        assert "course_id" in competency_func["parameters"]["properties"]
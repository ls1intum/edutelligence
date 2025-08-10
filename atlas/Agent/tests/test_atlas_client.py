import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os

# Add src directory to path for testing
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from atlas_client import AtlasAPIClient, Competency, SuggestCompetencyResponse


@pytest.fixture
def atlas_client():
    """Create AtlasAPIClient for testing."""
    return AtlasAPIClient(base_url="http://test-atlas", api_token="test-token")


@pytest.fixture
def mock_competencies():
    """Sample competencies for testing."""
    return [
        Competency(
            id="comp1",
            title="Sorting Algorithms",
            description="Understanding of basic sorting algorithms like bubble sort and merge sort",
            course_id="course1"
        ),
        Competency(
            id="comp2", 
            title="Data Structures",
            description="Knowledge of arrays, lists, and trees",
            course_id="course1"
        )
    ]


class TestAtlasAPIClient:
    """Test suite for AtlasAPIClient."""

    @pytest.mark.asyncio
    async def test_suggest_competencies_success(self, atlas_client, mock_competencies):
        """Test successful competency suggestion."""
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "competencies": [comp.model_dump() for comp in mock_competencies]
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            result = await atlas_client.suggest_competencies("sorting algorithms", "course1")
            
            assert len(result) == 2
            assert result[0].title == "Sorting Algorithms"
            assert result[1].title == "Data Structures"

    @pytest.mark.asyncio
    async def test_suggest_competencies_api_error(self, atlas_client):
        """Test API error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            with pytest.raises(Exception, match="Atlas API returned 500"):
                await atlas_client.suggest_competencies("test", "course1")

    @pytest.mark.asyncio
    async def test_suggest_competencies_timeout(self, atlas_client):
        """Test timeout handling."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            
            with pytest.raises(Exception, match="Atlas API request timed out"):
                await atlas_client.suggest_competencies("test", "course1")

    @pytest.mark.asyncio
    async def test_health_check_success(self, atlas_client):
        """Test successful health check."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            result = await atlas_client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, atlas_client):
        """Test failed health check."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection failed")
            )
            
            result = await atlas_client.health_check()
            assert result is False

    def test_format_competencies_for_display(self, atlas_client, mock_competencies):
        """Test competency formatting."""
        formatted = atlas_client.format_competencies_for_display(mock_competencies)
        
        assert "## Suggested Competencies:" in formatted
        assert "Sorting Algorithms" in formatted
        assert "Data Structures" in formatted
        assert "comp1" in formatted
        assert "comp2" in formatted

    def test_format_empty_competencies(self, atlas_client):
        """Test formatting empty competency list."""
        formatted = atlas_client.format_competencies_for_display([])
        assert formatted == "No competencies found."
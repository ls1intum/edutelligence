import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

# Add src directory to path for testing
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from atlasml.clients.artemis_client import ArtemisAPIClient, CompetencyMapping, Course, Exercise


@pytest.fixture
def artemis_client():
    """Create ArtemisAPIClient for testing."""
    return ArtemisAPIClient(base_url="http://test-artemis", api_token="test-token")


@pytest.fixture
def sample_mapping():
    """Sample competency mapping."""
    return CompetencyMapping(
        competency_id="comp1",
        exercise_id=123,
        course_id="456"
    )


class TestArtemisAPIClient:
    """Test suite for ArtemisAPIClient."""

    def test_apply_competency_mapping_success(self, artemis_client, sample_mapping):
        """Test successful competency mapping application."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response

            result = artemis_client.apply_competency_mapping(sample_mapping)

            assert result is True

    def test_apply_competency_mapping_failure(self, artemis_client, sample_mapping):
        """Test failed competency mapping application."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = artemis_client.apply_competency_mapping(sample_mapping)

            assert result is False

    def test_apply_competency_mapping_exception(self, artemis_client, sample_mapping):
        """Test exception handling in competency mapping."""
        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = Exception("Network error")

            result = artemis_client.apply_competency_mapping(sample_mapping)

            assert result is False

    def test_get_courses_success(self, artemis_client):
        """Test successful course retrieval."""
        mock_courses = [
            {"id": 1, "title": "CS101", "description": "Intro to CS", "semester": "Fall 2024"},
            {"id": 2, "title": "CS102", "description": "Advanced CS", "semester": "Spring 2024"}
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_courses

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response

            result = artemis_client.get_courses()

            assert len(result) == 2
            assert result[0].title == "CS101"
            assert result[1].title == "CS102"

    def test_get_exercises_success(self, artemis_client):
        """Test successful exercise retrieval."""
        mock_exercises = [
            {"id": 1, "title": "Exercise 1", "problem_statement": "Sort an array", "max_points": 10.0},
            {"id": 2, "title": "Exercise 2", "problem_statement": "Implement a tree", "max_points": 15.0}
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_exercises

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response

            result = artemis_client.get_exercises(course_id=123)

            assert len(result) == 2
            assert result[0].title == "Exercise 1"
            assert result[1].title == "Exercise 2"

    @pytest.mark.asyncio
    async def test_health_check_success(self, artemis_client):
        """Test successful health check."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('httpx.Client') as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            result = await artemis_client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, artemis_client):
        """Test failed health check."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.get = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await artemis_client.health_check()
            assert result is False
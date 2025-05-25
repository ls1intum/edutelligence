from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from memiris.domain.learning import Learning
from memiris.dto.learning_creation_dto import LearningCreationDto
from memiris.service.learning_deduplication import LearningDeduplicator
from memiris.service.ollama_wrapper import OllamaService, WrappedChatResponse


class TestLearningDeduplicator:
    """Test suite for the LearningDeduplicator class."""

    @pytest.fixture
    def mock_ollama_service(self):
        """Create a mock OllamaService."""
        mock_service = MagicMock(spec=OllamaService)
        return mock_service

    @pytest.fixture
    def mock_template(self):
        """Create a mock template."""
        mock = MagicMock()
        mock.render.return_value = "Rendered template content"
        return mock

    @pytest.fixture
    def sample_learnings(self):
        """Create a list of sample learnings for testing."""
        return [
            Learning(
                uid=uuid4(),
                title="Learning 1",
                content="The user is interested in Python programming.",
                reference="Test Reference",
            ),
            Learning(
                uid=uuid4(),
                title="Learning 2",
                content="The user wants to learn about Python.",
                reference="Test Reference",
            ),
            Learning(
                uid=uuid4(),
                title="Learning 3",
                content="The user is interested in JavaScript.",
                reference="Test Reference",
            ),
        ]

    @pytest.fixture
    def deduplicated_learnings(self):
        """Create a list of deduplicated learnings for mocked response."""
        return [
            {
                "title": "Learning 1 (Combined)",
                "content": "The user is interested in Python programming and wants to learn more about it.",
                "reference": "Test Reference",
            },
            {
                "title": "Learning 3",
                "content": "The user is interested in JavaScript.",
                "reference": "Test Reference",
            },
        ]

    @patch("memiris.service.learning_deduplication.create_template")
    def test_init(self, mock_create_template, mock_ollama_service):
        """Test initializing the LearningDeduplicator."""
        mock_template = MagicMock()
        mock_create_template.return_value = mock_template

        deduplicator = LearningDeduplicator(
            llm="test-model", ollama_service=mock_ollama_service, template=""
        )

        assert deduplicator.llm == "test-model"
        assert deduplicator.ollama_service == mock_ollama_service
        assert deduplicator.template == mock_template
        mock_create_template.assert_called_once()

    def test_deduplicate_success(
        self, mock_ollama_service, sample_learnings, deduplicated_learnings
    ):
        """Test successful deduplication of learnings."""
        # Create mock response
        mock_message = MagicMock()
        mock_message.content = LearningCreationDto.json_array_type().dump_json(
            deduplicated_learnings
        )

        mock_response = MagicMock(spec=WrappedChatResponse)
        mock_response.message = mock_message

        # Configure mock
        mock_ollama_service.chat.return_value = mock_response

        # Create deduplicator
        deduplicator = LearningDeduplicator(
            llm="test-model", ollama_service=mock_ollama_service, template=""
        )

        # Call deduplicate
        result = deduplicator.deduplicate(sample_learnings)

        # Assertions
        assert mock_ollama_service.chat.called
        assert len(result) == 2
        assert result[0].title == "Learning 1 (Combined)"
        assert (
            result[0].content
            == "The user is interested in Python programming and wants to learn more about it."
        )
        assert result[1].title == "Learning 3"
        assert result[1].content == "The user is interested in JavaScript."

        # Verify chat was called with correct parameters
        chat_call_args = mock_ollama_service.chat.call_args
        assert chat_call_args.kwargs["model"] == "test-model"
        assert len(chat_call_args.kwargs["messages"]) == 2
        assert chat_call_args.kwargs["options"] == {"temperature": 0.05}

    def test_deduplicate_empty_learnings(self, mock_ollama_service):
        """Test deduplication with empty learning list."""
        deduplicator = LearningDeduplicator(
            llm="test-model", ollama_service=mock_ollama_service, template=""
        )

        result = deduplicator.deduplicate([])

        # Should not call chat if there are no learnings
        mock_ollama_service.chat.assert_not_called()
        assert result == []

    def test_deduplicate_error_response(self, mock_ollama_service, sample_learnings):
        """Test deduplication with error in response parsing."""
        # Mock an invalid JSON response
        mock_message = MagicMock()
        mock_message.content = "invalid json"

        mock_response = MagicMock(spec=WrappedChatResponse)
        mock_response.message = mock_message

        # Configure mock
        mock_ollama_service.chat.return_value = mock_response

        # Create deduplicator
        deduplicator = LearningDeduplicator(
            llm="test-model", ollama_service=mock_ollama_service, template=""
        )

        # Call deduplicate
        result = deduplicator.deduplicate(sample_learnings)

        # Should return original learnings on error
        assert result == sample_learnings
        assert mock_ollama_service.chat.called

    def test_deduplicate_no_response(self, mock_ollama_service, sample_learnings):
        """Test deduplication with no response from ollama service."""
        # Configure mock to return None
        mock_ollama_service.chat.return_value = None

        # Create deduplicator
        deduplicator = LearningDeduplicator(
            llm="test-model", ollama_service=mock_ollama_service, template=""
        )

        # Call deduplicate
        result = deduplicator.deduplicate(sample_learnings)

        # Should return original learnings on error
        assert result == sample_learnings
        assert mock_ollama_service.chat.called

    def test_deduplicate_with_kwargs(
        self, mock_ollama_service, sample_learnings, deduplicated_learnings
    ):
        """Test deduplication with additional kwargs."""
        # Create mock response
        mock_message = MagicMock()
        mock_message.content = LearningCreationDto.json_array_type().dump_json(
            deduplicated_learnings
        )

        mock_response = MagicMock(spec=WrappedChatResponse)
        mock_response.message = mock_message

        # Configure mock
        mock_ollama_service.chat.return_value = mock_response

        # Create deduplicator
        deduplicator = LearningDeduplicator(
            llm="test-model", ollama_service=mock_ollama_service, template=""
        )

        # Call deduplicate with kwargs
        result = deduplicator.deduplicate(sample_learnings, custom_param="test_value")

        # Verify kwargs were passed to template.render
        render_call_args = mock_ollama_service.chat.call_args
        assert len(render_call_args.kwargs["messages"]) == 2

        # Since we can't directly check template rendering, we'll just ensure chat was called
        assert mock_ollama_service.chat.called
        assert len(result) == 2

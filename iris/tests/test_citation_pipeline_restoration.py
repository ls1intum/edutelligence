"""Tests for citation restoration functionality in CitationPipeline."""

from unittest.mock import MagicMock, patch

import pytest

from iris.pipeline.shared.citation_pipeline import CitationPipeline


class TestCitationRestoration:
    """Test suite for simplified citation format restoration."""

    @pytest.fixture
    def citation_pipeline(self):
        """Create a CitationPipeline instance for testing."""
        # Mock the LLM initialization to avoid requiring LLM_CONFIG_PATH
        with patch("iris.pipeline.shared.citation_pipeline.ModelVersionRequestHandler"):
            pipeline = CitationPipeline(local=True)
            # Mock the LLM-related attributes
            pipeline.keyword_summary_request_handler = MagicMock()
            return pipeline

    def test_restore_simple_to_full_lecture_page(self, citation_pipeline):
        """Test [cite:1] → [cite:L:123:5::!1] for lecture page citations."""
        answer = "Neural networks consist of layers. [cite:1]"
        citation_content_map = {
            1: {
                "content": "Neural networks...",
                "citation_id": "[cite:L:123:5::!1]",
                "type": "lecture_page",
                "lecture_unit_id": 123,
                "page_number": 5,
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        assert result == "Neural networks consist of layers. [cite:L:123:5::!1]"

    def test_restore_simple_to_full_lecture_transcription(self, citation_pipeline):
        """Test [cite:2] → [cite:L:456:12:120:180!2] for lecture transcription citations."""
        answer = "The backpropagation algorithm updates weights. [cite:2]"
        citation_content_map = {
            2: {
                "content": "Backpropagation...",
                "citation_id": "[cite:L:456:12:120:180!2]",
                "type": "lecture_transcription",
                "lecture_unit_id": 456,
                "page_number": 12,
                "start_time": 120,
                "end_time": 180,
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        assert (
            result
            == "The backpropagation algorithm updates weights. [cite:L:456:12:120:180!2]"
        )

    def test_restore_simple_to_full_faq(self, citation_pipeline):
        """Test [cite:3] → [cite:F:789:::!3] for FAQ citations."""
        answer = "The exam is on March 15th. [cite:3]"
        citation_content_map = {
            3: {
                "content": "Q: When is the exam? A: March 15th",
                "citation_id": "[cite:F:789:::!3]",
                "type": "faq",
                "faq_id": 789,
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        assert result == "The exam is on March 15th. [cite:F:789:::!3]"

    def test_restore_with_multiple_citations(self, citation_pipeline):
        """Test multiple citations in one answer are all restored."""
        answer = (
            "Neural networks consist of layers. [cite:1] "
            "The backpropagation algorithm updates weights. [cite:2] "
            "The exam is on March 15th. [cite:3]"
        )
        citation_content_map = {
            1: {
                "content": "Neural networks...",
                "citation_id": "[cite:L:123:5::!1]",
                "type": "lecture_page",
            },
            2: {
                "content": "Backpropagation...",
                "citation_id": "[cite:L:456:12:120:180!2]",
                "type": "lecture_transcription",
            },
            3: {
                "content": "Exam info...",
                "citation_id": "[cite:F:789:::!3]",
                "type": "faq",
            },
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        expected = (
            "Neural networks consist of layers. [cite:L:123:5::!1] "
            "The backpropagation algorithm updates weights. [cite:L:456:12:120:180!2] "
            "The exam is on March 15th. [cite:F:789:::!3]"
        )
        assert result == expected

    def test_restore_preserves_code_brackets(self, citation_pipeline):
        """Verify array[1] and other code with brackets is not affected."""
        answer = (
            "Access the array element array[1]. Neural networks are complex. [cite:2]"
        )
        citation_content_map = {
            2: {
                "content": "Neural networks...",
                "citation_id": "[cite:L:123:5::!2]",
                "type": "lecture_page",
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        # array[1] should remain unchanged, only [cite:2] should be replaced
        assert "array[1]" in result
        assert "[cite:L:123:5::!2]" in result
        assert "[cite:2]" not in result

    def test_restore_missing_citation_fallback(self, citation_pipeline):
        """Test that missing citation mappings keep the simple format as fallback."""
        answer = "Some text. [cite:99]"
        citation_content_map = {
            1: {
                "content": "Other content...",
                "citation_id": "[cite:L:123:5::!1]",
                "type": "lecture_page",
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        # [cite:99] should remain unchanged since it's not in the map
        assert result == "Some text. [cite:99]"

    def test_restore_repeated_citations(self, citation_pipeline):
        """Test that the same citation used multiple times is restored consistently."""
        answer = "First mention. [cite:1] Second mention. [cite:1]"
        citation_content_map = {
            1: {
                "content": "Neural networks...",
                "citation_id": "[cite:L:123:5::!1]",
                "type": "lecture_page",
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        assert (
            result
            == "First mention. [cite:L:123:5::!1] Second mention. [cite:L:123:5::!1]"
        )

    def test_restore_empty_answer(self, citation_pipeline):
        """Test that empty answers are handled gracefully."""
        answer = ""
        citation_content_map = {}

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        assert result == ""

    def test_restore_no_citations(self, citation_pipeline):
        """Test that answers without citations are returned unchanged."""
        answer = "This is just plain text without any citations."
        citation_content_map = {
            1: {
                "content": "Neural networks...",
                "citation_id": "[cite:L:123:5::!1]",
                "type": "lecture_page",
            }
        }

        result = citation_pipeline.restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        assert result == answer

    def test_integration_with_call_method(self, citation_pipeline):
        """Test that restoration integrates correctly with the full pipeline."""
        # Answer with simplified citations
        answer = "Neural networks consist of layers. [cite:1]"
        citation_content_map = {
            1: {
                "content": "Neural networks consist of interconnected layers that process information.",
                "citation_id": "[cite:L:123:5::!1]",
                "type": "lecture_page",
                "lecture_unit_id": 123,
                "page_number": 5,
            }
        }

        # The __call__ method should restore simple citations before enrichment
        result = citation_pipeline(
            answer=answer,
            citation_content_map=citation_content_map,
            user_language="en",
        )

        # Result should have full citation format with keyword and summary
        # Format: [cite:L:123:5::keyword:summary]
        assert "[cite:L:123:5:" in result
        assert "[cite:1]" not in result
        # The citation should be enriched with keyword and summary (two more fields after page)

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

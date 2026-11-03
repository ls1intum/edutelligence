"""Tool for retrieving FAQ content using RAG."""

from typing import Callable, Optional

from ..pipeline.shared.citation_sources import CitationSourceRegistry, source_id_line
from ..retrieval.faq_retrieval import FaqRetrieval
from ..retrieval.faq_retrieval_utils import format_faqs
from ..web.status.status_update import StatusCallback

EMPTY_QUERY_REPLY = (
    "Write a search query: name the question you need answered from the course FAQ."
)


def create_tool_faq_content_retrieval(
    faq_retriever: FaqRetrieval,
    course_id: int,
    callback: StatusCallback,
    citation_sources: Optional[CitationSourceRegistry] = None,
) -> Callable[[str], str]:
    """
    Create a tool that searches the course's FAQs for a query the agent writes.

    Args:
        faq_retriever: FAQ retrieval instance.
        course_id: Course ID.
        callback: Callback for status updates.
        citation_sources: When given, every FAQ gets a source id the agent can
            cite. Pipelines without citations pass nothing and get the plain output.

    Returns:
        The tool function.
    """
    del callback

    def faq_content_retrieval(query: str) -> str:
        """
        Search the course's FAQ (organization, enrollment, exam dates and rules,
        course structure). Use it for organizational questions about the course
        and for common questions an FAQ may answer.
        Write `query` as a short, self-contained question in the language of
        the course, for example "When is the exam registration deadline?".
        Each FAQ follows this format: FAQ ID, FAQ Question, FAQ Answer.
        Answer concisely and only from the relevant FAQs.

        Returns:
            str: Formatted string containing relevant FAQ answers.
        """
        if not query.strip():
            return EMPTY_QUERY_REPLY
        retrieved_faqs = faq_retriever(
            search_query=query, course_id=course_id, result_limit=10
        )

        if citation_sources is None:
            return format_faqs(retrieved_faqs)
        return "".join(
            source_id_line(citation_sources.register_faq(faq))
            + format_faqs([faq])
            + "\n"
            for faq in retrieved_faqs
        )

    return faq_content_retrieval

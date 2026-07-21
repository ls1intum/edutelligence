"""Tool for retrieving FAQ content using RAG."""

from typing import Any, Callable, Dict, List

from ..retrieval.faq_retrieval import FaqRetrieval
from ..retrieval.faq_retrieval_utils import format_faqs
from ..web.status.status_update import StatusCallback


def create_tool_faq_content_retrieval(
    faq_retriever: FaqRetrieval,
    course_id: int,
    course_name: str,
    base_url: str,
    callback: StatusCallback,
    query_text: str,
    history: List[Any],
    faq_storage: Dict[str, Any],
) -> Callable[[], str]:
    """
    Create a tool that retrieves FAQ content using RAG.

    Args:
        faq_retriever: FAQ retrieval instance.
        course_id: Course ID.
        course_name: Course name.
        base_url: Base URL for Artemis.
        callback: Callback for status updates.
        query_text: The student's query text.
        history: Chat history messages.
        faq_storage: Storage for retrieved FAQs.

    Returns:
        Callable[[], str]: Function that returns formatted FAQ content.
    """
    del callback

    def faq_content_retrieval() -> str:
        """
        Use this tool to retrieve information from indexed FAQs.
        This is the authoritative available source for official course logistics
        and rules, including deadlines, grace periods, eligibility, grading,
        enrollment, exams, and course structure. Use it for such questions even
        when another tool exposes a related date or exercise detail. It is also
        suitable for other common course questions that an FAQ could answer.
        The tool performs a RAG retrieval based on the chat history to find the most relevant FAQs.
        Each FAQ follows this format: FAQ ID, FAQ Question, FAQ Answer.
        Respond to the query concisely and solely using the answer from the relevant FAQs.
        This tool should only be used once per query.

        Returns:
            str: Formatted string containing relevant FAQ answers.
        """
        retrieved_faqs = faq_retriever(
            chat_history=history,
            student_query=query_text,
            result_limit=10,
            course_name=course_name,
            course_id=course_id,
            base_url=base_url,
        )

        # Store the retrieved FAQs for later use (e.g., citation pipeline)
        faq_storage["faqs"] = retrieved_faqs

        result = format_faqs(retrieved_faqs)
        return result

    return faq_content_retrieval

"""Tool for retrieving FAQ content using RAG."""

from typing import Any, Callable, Dict, List

from ..pipeline.shared.citation_utils import build_faq_citation_id
from ..retrieval.faq_retrieval import FaqRetrieval
from ..vector_database.faq_schema import FaqSchema
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
    citation_counter: Dict[str, int],
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
        citation_counter: Shared counter for citation sequence numbers.

    Returns:
        Callable[[], str]: Function that returns formatted FAQ content.
    """

    def faq_content_retrieval() -> str:
        """
        Use this tool to retrieve information from indexed FAQs.
        It is suitable when no other tool fits, it is a common question or the question is frequently asked,
        or the question could be effectively answered by an FAQ. Also use this if the question is explicitly
        organizational and course-related. An organizational question about the course might be
        "What is the course structure?" or "How do I enroll?" or exam related content like "When is the exam".
        The tool performs a RAG retrieval based on the chat history to find the most relevant FAQs.
        Each FAQ follows this format: FAQ ID, FAQ Question, FAQ Answer.
        Respond to the query concisely and solely using the answer from the relevant FAQs.
        This tool should only be used once per query.

        Returns:
            str: Formatted string containing relevant FAQ answers.
        """
        callback.in_progress("Retrieving faq content ...")
        retrieved_faqs = faq_retriever(
            chat_history=history,
            student_query=query_text,
            result_limit=10,
            course_name=course_name,
            course_id=course_id,
            base_url=base_url,
        )

        # Build citation content map with citation IDs created at retrieval time
        citation_content_map = {}

        for faq in retrieved_faqs:
            faq_props = faq.get("properties", {})
            faq_id = faq_props.get(FaqSchema.FAQ_ID.value)
            question = faq_props.get(FaqSchema.QUESTION_TITLE.value) or ""
            answer = faq_props.get(FaqSchema.QUESTION_ANSWER.value) or ""
            if not question and not answer:
                continue
            if not faq_id:
                continue
            seq_num = citation_counter.setdefault("next", 1)
            citation_counter["next"] += 1
            citation_id = build_faq_citation_id(faq_id, seq_num)
            citation_content_map[seq_num] = {
                "content": f"Q: {question}\nA: {answer}",
                "citation_id": citation_id,
                "type": "faq",
                "faq_id": faq_id,
            }

        # Store citation map
        faq_storage["citation_content_map"] = citation_content_map

        # Format result string with simplified citation IDs for LLM
        # Full citation IDs are stored in citation_content_map for later restoration
        result = "FAQ content:\n"
        for seq_num, citation_data in sorted(citation_content_map.items()):
            result += f'[cite:{seq_num}]\nContent:\n{citation_data["content"]}\n\n'

        return result

    return faq_content_retrieval

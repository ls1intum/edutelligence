"""Tool for retrieving lecture content using RAG."""

from typing import Any, Callable, Dict, List, Optional

from iris.common.logging_config import get_logger

from ..pipeline.shared.citation_utils import build_lecture_citation_id
from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import StatusCallback

logger = get_logger(__name__)


def _get_next_citation_number(citation_counter: Dict[str, int]) -> int:
    """
    Get next citation sequence number and increment counter.

    Args:
        citation_counter: Shared counter dict with 'next' key

    Returns:
        The next sequence number
    """
    seq_num = citation_counter.setdefault("next", 1)
    citation_counter["next"] += 1
    return seq_num


def create_tool_lecture_content_retrieval(
    lecture_retriever: LectureRetrieval,
    course_id: int,
    base_url: str,
    callback: StatusCallback,
    query_text: str,
    history: List[Any],
    lecture_content_storage: Dict[str, Any],
    citation_counter: Dict[str, int],
    lecture_id: Optional[int] = None,
    lecture_unit_id: Optional[int] = None,
) -> Callable[[], str]:
    """
    Create a tool that retrieves lecture content using RAG.

    Args:
        lecture_retriever: Lecture retrieval instance.
        course_id: Course ID.
        base_url: Base URL for Artemis.
        callback: Callback for status updates.
        query_text: The student's query text.
        history: Chat history messages.
        lecture_content_storage: Storage for retrieved content.
        citation_counter: Shared counter for citation sequence numbers.

    Returns:
        Callable[[], str]: Function that returns lecture content string.
    """

    def lecture_content_retrieval() -> str:
        """
        Retrieve content from indexed lecture content.
        This will run a RAG retrieval based on the chat history on the indexed lecture slides,
        the indexed lecture transcriptions and the indexed lecture segments,
        which are summaries of the lecture slide content and lecture transcription content from one slide a
        nd return the most relevant paragraphs.
        Use this if you think it can be useful to answer the student's question, or if the student explicitly asks
        a question about the lecture content or slides.
        Only use this once.

        Returns:
            str: Concatenated lecture slide, transcription, and segment content.
        """
        callback.in_progress("Retrieving lecture content ...")
        lecture_content = lecture_retriever(
            query=query_text,
            course_id=course_id,
            chat_history=history,
            lecture_id=lecture_id,
            lecture_unit_id=lecture_unit_id,
            base_url=base_url,
        )

        # Build citation content map with citation IDs created at retrieval time
        citation_content_map = {}

        # Process page chunks
        for paragraph in lecture_content.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            if not paragraph.lecture_unit_id:
                continue
            seq_num = _get_next_citation_number(citation_counter)
            citation_id = build_lecture_citation_id(
                paragraph.lecture_unit_id,
                paragraph.page_number,
                None,
                None,
                seq_num,
            )
            citation_content_map[seq_num] = {
                "content": paragraph.page_text_content,
                "citation_id": citation_id,
                "type": "lecture_page",
                "lecture_unit_id": paragraph.lecture_unit_id,
                "page_number": paragraph.page_number,
                "start_time": None,
                "end_time": None,
            }

        # Process transcriptions
        for paragraph in lecture_content.lecture_transcriptions:
            if not paragraph.segment_text:
                continue
            if not paragraph.lecture_unit_id:
                continue
            seq_num = _get_next_citation_number(citation_counter)
            try:
                start_time = (
                    int(paragraph.segment_start_time)
                    if paragraph.segment_start_time is not None
                    else None
                )
                end_time = (
                    int(paragraph.segment_end_time)
                    if paragraph.segment_end_time is not None
                    else None
                )
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Invalid time value in transcription, skipping timestamps: %s", e
                )
                start_time = None
                end_time = None
            citation_id = build_lecture_citation_id(
                paragraph.lecture_unit_id,
                paragraph.page_number,
                start_time,
                end_time,
                seq_num,
            )
            citation_content_map[seq_num] = {
                "content": paragraph.segment_text,
                "citation_id": citation_id,
                "type": "lecture_transcription",
                "lecture_unit_id": paragraph.lecture_unit_id,
                "page_number": paragraph.page_number,
                "start_time": start_time,
                "end_time": end_time,
            }

        # Process segments
        for paragraph in lecture_content.lecture_unit_segments:
            if not paragraph.segment_summary:
                continue
            if not paragraph.lecture_unit_id:
                continue
            seq_num = _get_next_citation_number(citation_counter)
            citation_id = build_lecture_citation_id(
                paragraph.lecture_unit_id,
                paragraph.page_number,
                None,
                None,
                seq_num,
            )
            citation_content_map[seq_num] = {
                "content": paragraph.segment_summary,
                "citation_id": citation_id,
                "type": "lecture_segment",
                "lecture_unit_id": paragraph.lecture_unit_id,
                "page_number": paragraph.page_number,
                "start_time": None,
                "end_time": None,
            }

        # Store citation map
        lecture_content_storage["citation_content_map"] = citation_content_map

        # Format result string with simplified citation IDs for LLM
        # Full citation IDs are stored in citation_content_map for later restoration
        # Group by type in a single pass for efficiency
        pages = []
        transcriptions = []
        segments = []

        for seq_num, citation_data in sorted(citation_content_map.items()):
            formatted = f'[cite:{seq_num}]\nContent:\n{citation_data["content"]}\n\n'
            if citation_data["type"] == "lecture_page":
                pages.append(formatted)
            elif citation_data["type"] == "lecture_transcription":
                transcriptions.append(formatted)
            elif citation_data["type"] == "lecture_segment":
                segments.append(formatted)

        result = ""
        if pages:
            result += "Lecture slide content:\n" + "".join(pages)
        if transcriptions:
            result += "Lecture transcription content:\n" + "".join(transcriptions)
        if segments:
            result += "Lecture segment content:\n" + "".join(segments)

        return result

    return lecture_content_retrieval

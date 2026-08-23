from weaviate.collections.classes.filters import Filter

from iris.config import settings
from iris.vector_database.course_memory_schema import CourseMemorySchema
from iris.vector_database.database import VectorDatabase


def should_allow_course_memory_tool(db: VectorDatabase, course_id: int) -> bool:
    """
    Check if course memory is enabled and there are stored entries for the course.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.

    Returns:
        bool: True if course memory is enabled and has entries for the course.
    """
    if not settings.course_memory.enabled:
        return False
    if course_id:
        result = db.course_memory.query.fetch_objects(
            filters=Filter.by_property(CourseMemorySchema.COURSE_ID.value).equal(
                course_id
            ),
            limit=1,
            return_properties=[CourseMemorySchema.MESSAGE_ID.value],
        )
        return len(result.objects) > 0
    return False


# Sources produced by tutor verification (Trigger A). THREAD_RESOLVED (Trigger B,
# any resolved thread) is NOT necessarily tutor-verified and must be labeled as such.
# The ingestion pipeline's provenance guard shares this set (TUTOR_VERIFIED_SOURCES
# in course_memory_ingestion_pipeline; kept there to avoid an import cycle).
_TUTOR_VERIFIED_SOURCES = {"IRIS_AUTO", "TUTOR_WRITTEN", "IRIS_CORRECTED"}


def build_thread_link(memory, base_url: str) -> str:
    """Artemis deep link to the thread an entry was mined from.

    The route mirrors the one Artemis builds server-side for its own communication
    notifications (``NewAnswerNotification``, ``IrisResponseNeedsReviewNotification`` and
    siblings), so a citation opens the original thread rather than merely naming it.

    Returns an empty string when the link cannot be built. That is the honest outcome for
    a run with no ``artemisBaseUrl`` or an entry stored before backlinking: a bare id is
    not something a student can follow, and half a URL is worse than none.
    """
    course_id = memory.get(CourseMemorySchema.COURSE_ID.value)
    conversation_id = memory.get(CourseMemorySchema.CONVERSATION_ID.value)
    post_id = memory.get(CourseMemorySchema.POST_ID.value)
    if not base_url or not course_id or not conversation_id or not post_id:
        return ""
    root = base_url.rstrip("/")
    return (
        f"{root}/courses/{course_id}/communication"
        f"?conversationId={conversation_id}&focusPostId={post_id}&openThreadOnFocus=1"
    )


def format_course_memories(retrieved_memories, base_url: str = "") -> str:
    """
    Format retrieved course memories into a string, including a link to the thread each
    answer came from so the agent can cite something a student can actually open.

    Entries are labeled by provenance: tutor-verified answers (Trigger A) vs.
    community-resolved answers (Trigger B, ``THREAD_RESOLVED``) that no tutor
    confirmed, so the agent can weight them accordingly.

    Args:
        retrieved_memories (List[dict]): List of retrieved memory property dicts.
        base_url (str): Artemis base URL used to build the thread link; when empty the
            entries are rendered without one.

    Returns:
        str: Formatted string, or a notice when no entries were found.
    """
    if not retrieved_memories:
        return "No relevant prior answers found."

    lines = []
    for memory in retrieved_memories:
        source = memory.get(CourseMemorySchema.SOURCE.value)
        label = (
            "Verified prior answer"
            if source in _TUTOR_VERIFIED_SOURCES
            else "Prior answer (community-resolved, not tutor-verified)"
        )
        link = build_thread_link(memory, base_url)
        # Only the link is offered as a citation target. The raw ids are ambiguous — Artemis
        # draws post and answer ids from separate sequences, so the same number identifies
        # two different messages — and mean nothing to a student either way.
        source_part = f"source: {link}, " if link else ""
        lines.append(
            f"[{label} | "
            f"{source_part}"
            f"question: {memory.get(CourseMemorySchema.QUESTION.value)}, "
            f"answer: {memory.get(CourseMemorySchema.ANSWER.value)}]"
        )
    return "\n".join(lines)

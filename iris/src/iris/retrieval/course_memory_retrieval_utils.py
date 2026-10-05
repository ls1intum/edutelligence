from typing import Iterable, Sequence

from weaviate.collections.classes.filters import Filter

from iris.common.artemis_instance import canonical_artemis_base_url
from iris.config import settings
from iris.domain.data.course_memory_dto import TUTOR_VERIFIED_SOURCES
from iris.vector_database.course_memory_schema import CourseMemorySchema
from iris.vector_database.database import VectorDatabase


def course_memory_scope_filter(base_url: str, course_id: int, allowed: Iterable[str]):
    """The filter every Course Memory read uses: live entries of this Artemis instance
    and course, from channels Artemis lists as readable by every student."""
    return (
        Filter.by_property(CourseMemorySchema.BASE_URL.value).equal(base_url)
        & Filter.by_property(CourseMemorySchema.COURSE_ID.value).equal(course_id)
        & Filter.by_property(CourseMemorySchema.DELETED.value).equal(False)
        & Filter.by_property(CourseMemorySchema.CONVERSATION_ID.value).contains_any(
            list(allowed)
        )
    )


def should_allow_course_memory_tool(
    db: VectorDatabase,
    *,
    course_id: int,
    base_url: str,
    allowed_conversation_ids: Sequence[int],
) -> bool:
    """
    Check if course memory is enabled and there are servable entries for the course.

    Only entries this run may serve count: live entries of the calling Artemis
    instance, from channels Artemis lists as readable by every student. Offering the
    tool for anything else would only cost a round-trip that returns nothing.

    Args:
        db (VectorDatabase): The vector database instance.
        course_id (int): The course ID.
        base_url (str): The base URL of the calling Artemis instance.
        allowed_conversation_ids (Sequence[int]): Channels readable by every student.

    Returns:
        bool: True if course memory is enabled and has servable entries for the course.
    """
    if not settings.course_memory.enabled or not course_id:
        return False
    if not allowed_conversation_ids:
        return False
    try:
        instance = canonical_artemis_base_url(base_url)
    except ValueError:
        return False
    allowed = [str(conversation_id) for conversation_id in allowed_conversation_ids]
    result = db.course_memory.query.fetch_objects(
        filters=course_memory_scope_filter(instance, course_id, allowed),
        limit=1,
        return_properties=[CourseMemorySchema.MESSAGE_ID.value],
    )
    return len(result.objects) > 0


def build_thread_link(memory) -> str:
    """Artemis deep link to the thread an entry was mined from.

    The path mirrors the route Artemis builds for its own communication deep links
    (``NewAnswerNotification``, global search results and siblings), so a citation
    opens the original thread rather than merely naming it.

    The link is deliberately **root-relative**. Iris's reply is only ever read from
    inside the Artemis client, so the browser is already on the right origin, and a
    relative href resolves correctly in every deployment. An absolute link built from
    ``artemisBaseUrl`` cannot: that value is ``server.url``, the address of the Spring
    Boot server, which is not the address the student's browser is on whenever the two
    differ — in the standard development setup the client runs on :9000 while
    ``server.url`` is :8080, so every citation opened a page that never bootstrapped.

    Returns an empty string when the path cannot be built. That is the honest outcome
    for an entry stored before backlinking: a bare id is not something a student can
    follow, and half a link is worse than none.
    """
    course_id = memory.get(CourseMemorySchema.COURSE_ID.value)
    conversation_id = memory.get(CourseMemorySchema.CONVERSATION_ID.value)
    post_id = memory.get(CourseMemorySchema.POST_ID.value)
    if not course_id or not conversation_id or not post_id:
        return ""
    return (
        f"/courses/{course_id}/communication"
        f"?conversationId={conversation_id}&focusPostId={post_id}&openThreadOnFocus=1"
    )


def format_course_memories(retrieved_memories) -> str:
    """
    Format retrieved course memories into a string, including a link to the thread each
    answer came from so the agent can cite something a student can actually open.

    Entries are labeled by provenance: tutor-verified answers (Trigger A) vs.
    community-resolved answers (Trigger B, ``THREAD_RESOLVED``) that no tutor
    confirmed, so the agent can weight them accordingly.

    Args:
        retrieved_memories (List[dict]): List of retrieved memory property dicts.

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
            if source in TUTOR_VERIFIED_SOURCES
            else "Prior answer (community-resolved, not tutor-verified)"
        )
        link = build_thread_link(memory)
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

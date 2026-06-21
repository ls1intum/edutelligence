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


def format_course_memories(retrieved_memories) -> str:
    """
    Format retrieved course memories into a string, including backlink ids so the
    agent can cite the originating message.

    Args:
        retrieved_memories (List[dict]): List of retrieved memory property dicts.

    Returns:
        str: Formatted string, or a notice when no entries were found.
    """
    if not retrieved_memories:
        return "No verified prior answers found."

    result = ""
    for memory in retrieved_memories:
        result += (
            "[Verified prior answer | "
            f"source message: {memory.get(CourseMemorySchema.MESSAGE_ID.value)}, "
            f"thread: {memory.get(CourseMemorySchema.CONVERSATION_ID.value)}, "
            f"question: {memory.get(CourseMemorySchema.QUESTION.value)}, "
            f"answer: {memory.get(CourseMemorySchema.ANSWER.value)}]"
        )
    return result

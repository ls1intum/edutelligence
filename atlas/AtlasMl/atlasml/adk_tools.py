"""ADK tools for Atlas and Artemis integration."""

import logging
from typing import Optional
from google.adk.tools import FunctionTool
from atlasml.ml.pipeline_workflows import PipelineWorkflows
from atlasml.clients.artemis_client import ArtemisAPIClient, CompetencyMapping

logger = logging.getLogger(__name__)

# Lazy initialization to avoid connection issues during import
def _get_pipeline():
    from atlasml.ml.pipeline_workflows import PipelineWorkflows
    return PipelineWorkflows()

def _get_artemis_client():
    return ArtemisAPIClient()

def get_competency_suggestions(description: str, course_id: str) -> str:
    """Get competency recommendations from Atlas based on a description.


    Args:
        description: Description to find similar competencies for
        course_id: ID of the course context

    Returns:
        Formatted competency suggestions
    """
    try:
        pipeline = _get_pipeline()
        competencies = pipeline.suggest_competencies_by_similarity(
            exercise_description=description,
            course_id=course_id,
            top_k=5
        )

        if competencies:
            formatted = _format_competencies_for_display(competencies)
            return formatted + "\n\nWould you like me to help you apply any of these competency mappings to specific exercises?"
        else:
            return "No competencies found for that description. Try with different keywords."
    except Exception as e:
        logger.error(f"Failed to get competency suggestions: {str(e)}")
        return f"Failed to get competency suggestions: {str(e)}"

def _format_competencies_for_display(competencies) -> str:
    """Format competencies for display to the user."""
    if not competencies:
        return "No competencies found."

    formatted = "## Suggested Competencies:\n\n"
    for i, comp in enumerate(competencies, 1):
        formatted += f"**{i}. {comp.title}**\n"
        formatted += f"   - *Description:* {comp.description}\n"
        formatted += f"   - *ID:* {comp.id}\n\n"

    return formatted

def get_courses(instructor_id: Optional[int] = None) -> str:
    """Get list of available courses from Artemis.

    Args:
        instructor_id: Optional instructor ID filter

    Returns:
        Formatted list of courses
    """
    try:
        artemis_client = _get_artemis_client()
        courses = artemis_client.get_courses(instructor_id)
        if courses:
            return artemis_client.format_courses_for_display(courses)
        else:
            return "No courses found. You may not have instructor access or there might be a connectivity issue."
    except Exception as e:
        logger.error(f"Failed to get courses: {str(e)}")
        return f"Failed to get courses: {str(e)}"

def get_exercises(course_id: str) -> str:
    """Get exercises for a specific course from Artemis.

    Args:
        course_id: ID of the course

    Returns:
        Formatted list of exercises
    """
    try:
        artemis_client = _get_artemis_client()
        exercises = artemis_client.get_exercises(course_id)
        if exercises:
            return artemis_client.format_exercises_for_display(exercises)
        else:
            return f"No exercises found for course {course_id}."
    except Exception as e:
        logger.error(f"Failed to get exercises: {str(e)}")
        return f"Failed to get exercises: {str(e)}"

'''@adk_tool
def apply_competency_mapping(competency_id: str, exercise_id: int, course_id: str) -> str:
    """Apply a competency mapping to an exercise.
    
    Args:
        competency_id: Atlas competency ID
        exercise_id: Artemis exercise ID  
        course_id: Artemis course ID
        
    Returns:
        Success or failure message
    """
    try:
        mapping = CompetencyMapping(
            competency_id=competency_id,
            exercise_id=exercise_id,
            course_id=course_id
        )
        success = artemis_client.apply_competency_mapping(mapping)

        if success:
            return f"✅ Successfully applied competency mapping: {competency_id} to exercise {exercise_id}"
        else:
            return "❌ Failed to apply competency mapping. Please try again or check your permissions."
    except Exception as e:
        logger.error(f"Failed to apply competency mapping: {str(e)}")
        return f"Failed to apply competency mapping: {str(e)}"'''


def map_competency_to_exercise(course_id: str, exercise_id: str, competency_id: str) -> str:
    """Map a competency to an exercise in Atlas.

    Args:
        course_id: Course ID for validation
        exercise_id: Exercise ID to map the competency to
        competency_id: Competency ID to map to the exercise

    Returns:
        Success or failure message
    """
    try:
        pipeline = _get_pipeline()
        pipeline.map_new_competency_to_exercise(
            exercise_id=exercise_id,
            competency_id=competency_id
        )
        return f"✅ Successfully mapped competency {competency_id} to exercise {exercise_id}"
    except ValueError as e:
        logger.error(f"Validation error in competency-exercise mapping: {str(e)}")
        return f"❌ Validation error: {str(e)}"
    except Exception as e:
        logger.error(f"Failed to map competency to exercise: {str(e)}")
        return f"❌ Failed to map competency to exercise: {str(e)}"


def map_competency_to_competency(course_id: str, source_competency_id: str, target_competency_id: str) -> str:
    """Create a relationship between two competencies in Atlas.

    Args:
        course_id: Course ID for validation
        source_competency_id: ID of the first competency
        target_competency_id: ID of the second competency to relate to

    Returns:
        Success or failure message
    """
    try:
        pipeline = _get_pipeline()
        pipeline.map_competency_to_competency(
            source_competency_id=source_competency_id,
            target_competency_id=target_competency_id
        )
        return f"✅ Successfully created relationship between competencies {source_competency_id} and {target_competency_id}"
    except ValueError as e:
        logger.error(f"Validation error in competency-competency mapping: {str(e)}")
        return f"❌ Validation error: {str(e)}"
    except Exception as e:
        logger.error(f"Failed to map competency to competency: {str(e)}")
        return f"❌ Failed to map competency to competency: {str(e)}"

# List of all tools for easy import
atlas_artemis_tools = [
    FunctionTool(get_competency_suggestions),
    FunctionTool(get_courses),
    FunctionTool(get_exercises),
    FunctionTool(map_competency_to_exercise),
    FunctionTool(map_competency_to_competency)
]
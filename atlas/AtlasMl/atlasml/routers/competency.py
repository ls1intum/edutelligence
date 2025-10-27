"""
Competency endpoints for AtlasML.

This router exposes endpoints to:
- Suggest competencies similar to a given description
- Persist competencies and exercises with an operation type
- Suggest competency relations (currently generated heuristically)

All endpoints are versioned under `/api/v1/competency`.
Request/response models are defined in `atlasml.models.competency`.
"""

import logging
import random
from fastapi import APIRouter, HTTPException, Depends

from atlasml.ml.pipeline_workflows import PipelineWorkflows
from atlasml.models.competency import (
    SaveCompetencyRequest,
    SuggestCompetencyRequest,
    SuggestCompetencyResponse,
    CompetencyRelation,
    CompetencyRelationSuggestionResponse,
    RelationType,
    MapNewCompetencyToExerciseRequest,
    MapCompetencyToCompetencyRequest,
)
from atlasml.utils import (
    handle_pipeline_error,
    validate_non_empty_string,
    safe_get_attribute,
)
from atlasml.dependencies import TokenValidator
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/competency", tags=["competency"])


@router.post(
    "/suggest",
    response_model=SuggestCompetencyResponse,
    dependencies=[],
)
async def suggest_competencies(
    request: SuggestCompetencyRequest,
) -> SuggestCompetencyResponse:
    """
    Suggest competencies based on semantic similarity of the input description.

    Args:
        request: Pydantic model with `description` and `course_id`.

    Returns:
        SuggestCompetencyResponse: A list of matching `Competency` items.

    Raises:
        HTTPException: 400 on validation errors, 500 on internal failures.
    """
    try:
        logger.info(
            f"Suggesting competencies for description: {request.description[:100]}..."
        )

        # Validate input using utility function
        validated_description = validate_non_empty_string(
            request.description, "description"
        )

        pipeline = PipelineWorkflows()
        competencies = pipeline.suggest_competencies_by_similarity(
            validated_description, course_id=request.course_id
        )

        logger.info(f"Successfully suggested {len(competencies)} competencies")
        return SuggestCompetencyResponse(competencies=competencies)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Use centralized error handling
        raise handle_pipeline_error(e, "suggest_competencies")


@router.post("/save", dependencies=[])
async def save_competencies(request: SaveCompetencyRequest):
    """
    Save competencies and/or a single exercise with an operation type.

    Args:
        request: Pydantic model with optional `competencies`, optional `exercise`,
            and an `operation_type` (UPDATE/DELETE).

    Returns:
        200 OK on success with an empty body.

    Raises:
        HTTPException: 400 on validation errors, 500 on internal failures.
    """
    try:
        logger.info(
            f"Saving competencies with operation type: {request.operation_type}"
        )

        # Validate that at least one item is provided
        if not request.competencies and not request.exercise:
            raise ValueError("At least one competency or exercise must be provided")

        # Validate operation type
        validated_operation_type = validate_non_empty_string(
            request.operation_type, "operation_type"
        )

        pipeline = PipelineWorkflows()
        saved_items = []

        # Save competencies if provided
        if request.competencies:
            try:
                logger.info(f"Saving {len(request.competencies)} competencies")
                result = pipeline.save_competencies(
                    request.competencies, validated_operation_type
                )
                saved_items.append({"type": "competencies", "result": result})
                logger.info("All competencies saved and reclustered successfully")
            except Exception as e:
                logger.error(f"Failed to save competencies: {e}")
                raise Exception(f"Failed to save competencies: {str(e)}")

        # Save exercise if provided
        if request.exercise:
            try:
                exercise_desc = safe_get_attribute(request.exercise, "description")
                logger.info(f"Saving exercise: {exercise_desc}")
                result = pipeline.save_exercise(
                    request.exercise, validated_operation_type
                )
                saved_items.append({"type": "exercise", "result": result})
                logger.info("Exercise saved successfully")
            except Exception as e:
                logger.error(f"Failed to save exercise: {e}")
                raise Exception(f"Failed to save exercise: {str(e)}")

        logger.info(f"Successfully saved {len(saved_items)} items")
        # Return 200 OK response without body
        return

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Use centralized error handling
        raise handle_pipeline_error(e, "save_competencies")


@router.get(
    "/relations/suggest/{course_id}",
    response_model=CompetencyRelationSuggestionResponse,
    dependencies=[],
)
async def suggest_competency_relations(course_id: int) -> CompetencyRelationSuggestionResponse:
    """
    Suggest directed relations between competencies for a course.

    The current implementation relies on the pipeline to produce relation
    suggestions; it may (temporarily) be heuristic.
    """
    try:
        logger.info(f"Suggesting competency relations for course_id={course_id}")

        pipeline = PipelineWorkflows()
        relations = pipeline.suggest_competency_relations(course_id)

        logger.info(f"Suggested {len(relations.relations)} competency relations")
        return relations

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Use centralized error handling
        raise handle_pipeline_error(e, "suggest_competency_relations")


@router.post("/map-competency-to-exercise",dependencies=[])
async def map_new_competency_to_exercise(request: MapNewCompetencyToExerciseRequest):
    """
    Map a new competency to an existing exercise.

    Args:
        request: Request containing exercise_id and competency_id to map

    Returns:
        200 OK HTTP response on successful mapping

    Raises:
        HTTPException: 400 for validation errors, 500 for server errors
    """
    try:
        logger.info(
            f"Mapping competency {request.competency_id} to exercise {request.exercise_id}"
        )

        pipeline = PipelineWorkflows()
        pipeline.map_new_competency_to_exercise(
            request.exercise_id, request.competency_id
        )

        logger.info(
            f"Successfully mapped competency {request.competency_id} to exercise {request.exercise_id}"
        )
        return

    except HTTPException:
        raise
    except Exception as e:
        raise handle_pipeline_error(e, "map_new_competency_to_exercise")


@router.post("/map-competency-to-competency",dependencies=[])
async def map_competency_to_competency(request: MapCompetencyToCompetencyRequest):
    """
    Map a competency to another competency (bidirectional relationship).

    Args:
        request: Request containing source_competency_id and target_competency_id to map

    Returns:
        200 OK HTTP response on successful mapping

    Raises:
        HTTPException: 400 for validation errors, 500 for server errors
    """
    try:
        logger.info(
            f"Mapping competency {request.source_competency_id} to competency {request.target_competency_id}"
        )

        pipeline = PipelineWorkflows()
        pipeline.map_competency_to_competency(
            request.source_competency_id, request.target_competency_id
        )

        logger.info(
            f"Successfully mapped competency {request.source_competency_id} to competency {request.target_competency_id}"
        )
        return

    except HTTPException:
        raise
    except Exception as e:
        raise handle_pipeline_error(e, "map_competency_to_competency")

import logging
from fastapi import APIRouter, HTTPException, Depends

from atlasml.ml.pipeline_workflows import PipelineWorkflows
from atlasml.models.competency import (
    SaveCompetencyRequest,
    SuggestCompetencyRequest,
    SuggestCompetencyResponse,
)
from atlasml.utils import handle_pipeline_error, validate_non_empty_string, safe_get_attribute
from atlasml.dependencies import TokenValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/competency", tags=["competency"])

@router.post(
    "/suggest",
    response_model=SuggestCompetencyResponse,
    dependencies=[Depends(TokenValidator)],
)
async def suggest_competencies(request: SuggestCompetencyRequest) -> SuggestCompetencyResponse:
    """
    Suggest competencies based on similarity to the provided description.
    
    Args:
        request: Request containing description for competency suggestion
        
    Returns:
        SuggestCompetencyResponse with suggested competencies
        
    Raises:
        HTTPException: 400 for validation errors, 500 for server errors
    """
    try:
        logger.info(f"Suggesting competencies for description: {request.description[:100]}...")
        
        # Validate input using utility function
        validated_description = validate_non_empty_string(request.description, "description")
            
        pipeline = PipelineWorkflows()
        competencies = pipeline.suggest_competencies_by_similarity(validated_description)
        
        logger.info(f"Successfully suggested {len(competencies)} competencies")
        return SuggestCompetencyResponse(competencies=competencies)
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Use centralized error handling
        raise handle_pipeline_error(e, "suggest_competencies")


@router.post(
    "/save", dependencies=[Depends(TokenValidator)]
)
async def save_competencies(request: SaveCompetencyRequest):
    """
    Save competencies and/or exercises with the specified operation type.
    
    Args:
        request: Request containing competency/exercise data and operation type
        
    Returns:
        200 OK HTTP response on successful save
        
    Raises:
        HTTPException: 400 for validation errors, 500 for server errors
    """
    try:
        logger.info(f"Saving competencies with operation type: {request.operation_type}")
        
        # Validate that at least one item is provided
        if not request.competency and not request.exercise:
            raise ValueError("At least one competency or exercise must be provided")
            
        # Validate operation type
        validated_operation_type = validate_non_empty_string(request.operation_type, "operation_type")
            
        pipeline = PipelineWorkflows()
        saved_items = []
        
        # Save competency if provided
        if request.competency:
            try:
                competency_name = safe_get_attribute(request.competency, 'title')
                logger.info(f"Saving competency: {competency_name}")
                result = pipeline.save_competency(request.competency, validated_operation_type)
                saved_items.append({"type": "competency", "result": result})
                logger.info("Competency saved successfully")
            except Exception as e:
                logger.error(f"Failed to save competency: {e}")
                raise Exception(f"Failed to save competency: {str(e)}")
        
        # Save exercise if provided
        if request.exercise:
            try:
                exercise_desc = safe_get_attribute(request.exercise, 'description')
                logger.info(f"Saving exercise: {exercise_desc}")
                result = pipeline.save_exercise(request.exercise, validated_operation_type)
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

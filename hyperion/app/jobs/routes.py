"""
API routes for the job system.
"""
from typing import Optional, Annotated, TypeVar, Generic

from fastapi import APIRouter, status, Depends, BackgroundTasks, Header
from fastapi.responses import JSONResponse
from pydantic import HttpUrl, Field, BaseModel

# Import base models
from app.actions.base_models import (
    JobCreateRequest, 
    Job, 
    JobStatusResponse, 
    ActionInput,
    ActionUpdate
)

from app.actions import autodiscover_handlers
from app.actions.model_registry import autodiscover_models

# Register all action handlers
autodiscover_handlers()

# Discover and register all action models
autodiscover_models()


# Import the model registry which handles dynamic type unions
from app.actions.model_registry import get_input_union, get_update_union

# Import service
from app.jobs.service import JobService

# Get dynamic union types from the registry
ActionInputUnion = get_input_union()
ActionUpdateUnion = get_update_union()

# Create a job response class with a clean name for OpenAPI
class JobResponse(Job[ActionInputUnion, ActionUpdateUnion]):
    """Job response model with proper schema name."""
    
    model_config = {
        "json_schema_extra": {"title": "Job"}
    }

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    responses={
        404: {"description": "Not found"},
        500: {"description": "Internal server error"},
    },
)

# Create a dependency that provides JobService with BackgroundTasks
def get_job_service(background_tasks: BackgroundTasks) -> JobService:
    """Dependency that provides JobService with BackgroundTasks."""
    return JobService(background_tasks)

class JobRequest(BaseModel):
    """
    Job creation request model with discriminated union for action-specific input data.
    This allows the OpenAPI schema to properly document the different possible input types.
    """
    action_name: str = Field(..., description="Name of the AI action to perform.")
    input_data: ActionInputUnion = Field(..., description="Input data for the AI action.")

@router.post(
    "/",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a new background job for an AI action",
    description=(
        "Creates a new job to be processed in the background. "
        "The caller provides an action name and input data in the request body, "
        "and callback URL and an optional callback auth secret in headers."
    ),
    responses={
        202: {
            "description": "Job accepted",
            "model": JobResponse,
        }
    }
)
async def create_new_job(
    job_request: JobRequest,
    callback_url: HttpUrl = Header(..., description="URL to send status updates and final results."),
    x_callback_auth_secret: Optional[str] = Header(None, alias="X-Callback-Auth-Secret", description="Secret for callback authentication."),
    job_service: JobService = Depends(get_job_service)
):
    """
    Create a new job. The actual processing will be done in the background.
    The `action_name` in the request body determines which AI task to run.
    The `input_data` should match the expected schema for that `action_name`.
    Callback URL and auth secret are provided in headers.
    """
    # Validate that action_name matches the action in input_data
    if job_request.action_name != job_request.input_data.action:
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"Action name '{job_request.action_name}' in request doesn't match action '{job_request.input_data.action}' in input data."
            },
        )
    
    # Create a job request with appropriate typing
    typed_request = JobCreateRequest[ActionInput](
        action_name=job_request.action_name,
        input_data=job_request.input_data
    )
    
    created_job = await job_service.create_job(
        job_request=typed_request,
        callback_url=callback_url,
        callback_auth_secret=x_callback_auth_secret
    )
    
    return created_job


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get job status and results",
    description="Retrieves the current status of a job, along with any updates and final results."
)
async def get_job_status_by_id(
    job_id: str,
    job_service: JobService = Depends(get_job_service)
):
    """
    Get the status of a specific job by its ID.
    """
    job = await job_service.get_job_status(job_id)
    
    return JobStatusResponse(
        job_id=job.job_id,
        action_name=job.action_name,
        status=job.status,
        updates=job.updates,
        final_result=job.final_result,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
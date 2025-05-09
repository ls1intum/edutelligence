"""
Job management service.

This service handles the creation, tracking, and execution of background jobs.
It manages sending callbacks with status updates and results.

For a production system, you would replace the in-memory job store with a persistent
database (e.g., Redis, PostgreSQL, MongoDB) and a task queue (e.g., Celery, RQ).
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Generic, Optional

import httpx
from fastapi import HTTPException, BackgroundTasks
from pydantic import HttpUrl

from app.actions import (
    get_action_handler, 
)
from app.actions.base_models import (
    ActionUpdate,
    JobStatus
)

from app.actions.base_models import (
    Job, 
    JobCreateRequest, 
    CallbackPayload, 
    CallbackAuth,
    ActionInputT,
    ActionUpdateT
)
from app.logger import logger

# In-memory store for jobs. Replace with a database in production.
jobs_db: Dict[str, Job] = {}

async def send_callback(job: Job, status: JobStatus, update: Optional[ActionUpdate] = None, error: Optional[str] = None):
    """Sends a callback to the specified URL for a job."""
    payload = CallbackPayload(
        job_id=job.job_id,
        action_name=job.action_name,
        status=status,
        timestamp=datetime.now(timezone.utc).isoformat(),
        update=update,
        error=error,
    )
    headers = {"Content-Type": "application/json"}
    if job.callback_auth:
        headers[job.callback_auth.header_name] = job.callback_auth.secret

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(str(job.callback_url), json=payload.model_dump(exclude_none=True), headers=headers)
            response.raise_for_status()
            logger.info(f"Callback sent successfully for job {job.job_id} to {job.callback_url}, status: {status}")
        except httpx.RequestError as e:
            logger.error(f"Error sending callback for job {job.job_id} to {job.callback_url}: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Callback for job {job.job_id} to {job.callback_url} failed with status {e.response.status_code}: {e.response.text}")

async def process_job(job_id: str):
    """Processes a job by executing the registered action handler."""
    job = jobs_db.get(job_id)
    if not job:
        logger.error(f"Job {job_id} not found for processing.")
        return

    try:
        # Get the appropriate handler for this action
        handler_cls = get_action_handler(job.action_name)
        handler = handler_cls()
    except ValueError as e:
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        job.updated_at = datetime.now(timezone.utc).isoformat()
        await send_callback(job, JobStatus.FAILED, error=job.error_message)
        logger.error(job.error_message)
        return

    job.status = JobStatus.IN_PROGRESS
    job.updated_at = datetime.now(timezone.utc).isoformat()
    await send_callback(job, JobStatus.IN_PROGRESS)
    logger.info(f"Processing job {job.job_id} for action '{job.action_name}'.")

    # Define the action update function to be passed to the handler
    async def send_action_update(update: ActionUpdate):
        # Always set timestamp if not provided
        if not update.timestamp:
            update.timestamp = datetime.now(timezone.utc).isoformat()
            
        # Store update for GET /job/{id} status endpoint
        job.updates.append(update)
        job.updated_at = datetime.now(timezone.utc).isoformat()
        
        # By convention, we consider updates with type ending with "_result" as final results
        # This allows each action to have its own specific result type
        if update.update_type.endswith("_result"):
            job.status = JobStatus.COMPLETED
            await send_callback(job, JobStatus.COMPLETED, update=update)
            logger.info(f"Job {job.job_id} completed successfully with final result.")
        else:
            # Send the intermediate update via callback
            await send_callback(job, JobStatus.IN_PROGRESS, update=update)
            logger.info(f"Sent update for job {job.job_id}.")

    try:
        # Let the handler process the job
        result = await handler.handle(job.input_data, send_action_update)
        
        # In case the handler didn't explicitly send a result update
        if job.status != JobStatus.COMPLETED:
            # Ensure timestamp is set
            if not result.timestamp:
                result.timestamp = datetime.now(timezone.utc).isoformat()
            
            # Add the final result update
            job.updates.append(result)
            job.status = JobStatus.COMPLETED
            job.updated_at = datetime.now(timezone.utc).isoformat()
            await send_callback(job, JobStatus.COMPLETED, update=result)
            logger.info(f"Job {job.job_id} completed successfully.")
    except Exception as e:
        logger.exception(f"Error processing job {job.job_id}: {e}")
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        job.updated_at = datetime.now(timezone.utc).isoformat()
        await send_callback(job, JobStatus.FAILED, error=job.error_message)


class JobService(Generic[ActionInputT, ActionUpdateT]):
    """Service for managing jobs asynchronously."""
    
    def __init__(self, background_tasks: BackgroundTasks):
        self.background_tasks = background_tasks

    async def create_job(
        self, 
        job_request: JobCreateRequest[ActionInputT],
        callback_url: HttpUrl,
        callback_auth_secret: Optional[str],
        callback_auth_header_name: str = "X-Callback-Auth"
    ) -> Job[ActionInputT, ActionUpdateT]:
        """
        Create a new job to be processed asynchronously.
        
        Args:
            job_request: The job creation request
            callback_url: URL to send job updates to
            callback_auth_secret: Optional secret for authenticating callbacks
            callback_auth_header_name: Header name for callback authentication
            
        Returns:
            The created job
            
        Raises:
            HTTPException: If the action is not registered
        """
        # Validate that we have a handler for this action
        try:
            get_action_handler(job_request.action_name)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"AI action '{job_request.action_name}' not registered.")

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        auth_details = None
        if callback_auth_secret:
            auth_details = CallbackAuth(header_name=callback_auth_header_name, secret=callback_auth_secret)
            
        job = Job[
            ActionInputT, ActionUpdateT
        ](
            job_id=job_id,
            action_name=job_request.action_name,
            status=JobStatus.PENDING,
            input_data=job_request.input_data,
            callback_url=callback_url,
            callback_auth=auth_details,
            created_at=now,
            updated_at=now,
        )
        jobs_db[job_id] = job
        logger.info(f"Created job {job_id} for action '{job.action_name}'. Callback to: {job.callback_url}")

        self.background_tasks.add_task(process_job, job_id)
        await send_callback(job, JobStatus.PENDING) 
        return job
        
    async def get_job_status(self, job_id: str) -> Job:
        """
        Get the status of a job by its ID.
        
        Args:
            job_id: The unique identifier of the job
            
        Returns:
            The current job information
            
        Raises:
            HTTPException: If the job is not found
        """
        job = jobs_db.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
        return job

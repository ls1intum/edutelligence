"""
Base models for all AI actions.

This module defines the common interfaces and base classes that all AI actions
should implement to ensure consistency and type safety across the application.
"""

from enum import Enum
from typing import (
    Awaitable,
    Callable,
    Generic,
    TypeVar,
    Optional,
    Protocol,
    runtime_checkable,
)
from pydantic import BaseModel, Field, HttpUrl

# Type variables for generic inputs and updates
ActionInputT = TypeVar("ActionInputT", bound="ActionInput")
ActionUpdateT = TypeVar("ActionUpdateT", bound="ActionUpdate")


class JobStatus(str, Enum):
    """Status states for a job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionInput(BaseModel):
    """Base class for all AI action inputs."""

    action: str = Field(..., description="The action this input is for.")


class ActionUpdate(BaseModel):
    """Base class for all action updates, including progress updates and final results."""

    update_type: str = Field(
        ..., description="Type of update defined by the specific action."
    )
    timestamp: Optional[str] = Field(
        None, description="Timestamp when this update was generated."
    )


class JobCreateRequest(BaseModel, Generic[ActionInputT]):
    """Request to create a new job."""

    action_name: str = Field(..., description="Name of the AI action to perform.")
    input_data: ActionInputT = Field(..., description="Input data for the AI action.")


class CallbackAuth(BaseModel):
    """Authentication details for job callbacks."""

    header_name: str = "X-Callback-Auth"
    secret: str


class Job(BaseModel, Generic[ActionInputT, ActionUpdateT]):
    """A job for processing an AI action asynchronously."""

    job_id: str = Field(..., description="Unique identifier for the job.")
    action_name: str = Field(..., description="Name of the AI action.")
    status: JobStatus = Field(
        default=JobStatus.PENDING, description="Current status of the job."
    )
    input_data: ActionInputT = Field(..., description="Input data for the AI action.")
    callback_url: HttpUrl = Field(..., description="URL for callback.")
    callback_auth: Optional[CallbackAuth] = Field(
        None, description="Authentication for callback."
    )
    updates: list[ActionUpdateT] = Field(
        default_factory=list, description="All updates for this job."
    )
    error_message: Optional[str] = Field(
        None, description="Error message if the job failed."
    )
    created_at: str = Field(..., description="Timestamp of job creation.")
    updated_at: str = Field(..., description="Timestamp of last update.")

    @property
    def final_result(self) -> Optional[ActionUpdateT]:
        """Get the final result, which is the last update when job is completed."""
        if self.status == JobStatus.COMPLETED and self.updates:
            return self.updates[-1]
        return None

    # Workaround to set the name of the class to "Job" in the OpenAPI schema
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__name__ = "Job"


class JobStatusResponse(BaseModel, Generic[ActionUpdateT]):
    """Response for a job status request."""

    job_id: str
    action_name: str
    status: JobStatus
    updates: list[ActionUpdateT] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: str
    updated_at: str

    @property
    def final_result(self) -> Optional[ActionUpdateT]:
        """Get the final result, which is the last update when job is completed."""
        if self.status == JobStatus.COMPLETED and self.updates:
            return self.updates[-1]
        return None

    # Workaround to set the name of the class to "JobStatusResponse" in the OpenAPI schema
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__name__ = "JobStatusResponse"


class CallbackPayload(BaseModel, Generic[ActionUpdateT]):
    """Payload sent in callbacks for job status updates."""

    job_id: str = Field(..., description="Unique identifier for the job.")
    action_name: str = Field(..., description="Name of the AI action.")
    status: JobStatus = Field(..., description="Current status of the job.")
    timestamp: str = Field(..., description="Timestamp of when this callback was sent.")
    update: Optional[ActionUpdateT] = Field(
        None, description="Latest update data for the job."
    )
    error: Optional[str] = Field(None, description="Error message if the job failed.")


ActionUpdateCallback = Callable[[ActionUpdate], Awaitable[None]]


@runtime_checkable
class ActionHandler(Protocol):
    """Protocol defining the interface for action handlers."""

    action_name: str

    async def handle(
        self, input_data: ActionInput, send_update: ActionUpdateCallback
    ) -> ActionUpdate:
        """Handle the execution of an action."""
        ...

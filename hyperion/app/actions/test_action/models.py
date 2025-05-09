"""
Models for the test action.
This is a sample action to demonstrate the dynamic model registry.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field

from app.actions.base_models import ActionInput, ActionUpdate


class TestActionInput(ActionInput):
    """Input model for test action."""

    action: Literal["test_action"] = "test_action"
    text: str = Field(..., description="Text to process")
    language: str = Field("en", description="Language code")
    options: Optional[dict] = Field(
        None, description="Additional options for processing"
    )


class TestItem(BaseModel):
    """An item in the test results."""

    id: str = Field(..., description="Unique identifier for this item")
    content: str = Field(..., description="Content of the test item")
    score: float = Field(..., ge=0, le=1, description="Score between 0 and 1")


class TestActionProgressUpdate(ActionUpdate):
    """Progress update for test action."""

    update_type: Literal["test_action_progress"] = "test_action_progress"
    status_message: str = Field(..., description="Current status message")
    progress: Optional[float] = Field(
        None, ge=0, le=100, description="Progress percentage"
    )
    items_processed: Optional[int] = Field(
        None, description="Number of items processed"
    )


class TestActionResult(ActionUpdate):
    """Final result for test action."""

    update_type: Literal["test_action_result"] = "test_action_result"
    items: List[TestItem] = Field(default_factory=list, description="Processed items")
    summary: str = Field(..., description="Summary of the processing")
    total_score: float = Field(..., ge=0, description="Total score of all items")

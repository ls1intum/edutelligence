from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field

from app.actions.base_models import ActionInput, ActionUpdate

class ConsistencyCheckInput(ActionInput):
    """Input model for consistency check action."""
    action: Literal["consistency_check"] = "consistency_check"
    problem_statement: str = Field(..., description="The description of the exercise containing tasks")
    template_repository: Dict[str, str] = Field(..., description="Files in the template repository, mapping file paths to content")
    solution_repository: Dict[str, str] = Field(..., description="Files in the solution repository, mapping file paths to content")
    test_repository: Optional[Dict[str, str]] = Field(default_factory=dict, description="Files in the test repository, mapping file paths to content")

class ConsistencyIssue(BaseModel):
    """Data model representing a consistency issue found in the exercise."""
    file_path: str = Field(..., description="Path to the file with consistency issue")
    description: str = Field(..., description="Description of the consistency issue")

class ConsistencyCheckProgressUpdate(ActionUpdate):
    """Progress update for consistency check action."""
    update_type: Literal["consistency_check_progress"] = "consistency_check_progress"
    status_message: str = Field(..., description="Current status message of the consistency checking process.")
    progress: Optional[float] = Field(None, ge=0, le=100, description="Optional progress indicator as percentage.")
    files_processed: Optional[int] = Field(None, description="Number of files processed so far.")
    total_files: Optional[int] = Field(None, description="Total number of files to process.")

class ConsistencyCheckResult(ActionUpdate):
    """Final result for consistency check action."""
    update_type: Literal["consistency_check_result"] = "consistency_check_result"
    issues: List[ConsistencyIssue] = Field(default_factory=list, description="List of consistency issues found")
    summary: str = Field("", description="A summary of all consistency issues")
    status: str = Field("success", description="Status of the consistency check")
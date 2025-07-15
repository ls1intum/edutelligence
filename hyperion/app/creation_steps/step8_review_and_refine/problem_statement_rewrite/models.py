from pydantic import BaseModel, Field


class RewriteProblemStatementRequest(BaseModel):
    """Request model for problem statement rewriting"""

    text: str = Field(..., description="Text to rewrite")


class RewriteProblemStatementResponse(BaseModel):
    """Response model for problem statement rewriting"""

    rewritten_text: str = Field(..., description="Rewritten text")

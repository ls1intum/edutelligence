from typing import Sequence

from pydantic import BaseModel, Field


class FileGradingInstruction(BaseModel):
    file_name: str = Field(description="File name")
    grading_instructions: str = Field(description="Grading instructions relevant for this file")


class SplitGradingInstructionsByFileOutput(BaseModel):
    """Collection of grading instructions split by file"""
    items: Sequence[FileGradingInstruction] = Field(description="File grading instructions")
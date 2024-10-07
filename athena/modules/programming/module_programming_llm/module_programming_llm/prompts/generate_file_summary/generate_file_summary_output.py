from typing import Dict

from pydantic import BaseModel, Field


class FileDescription(BaseModel):
    file_path: str = Field(description="The path of the file, as specified in the input prompt")
    description: str = Field(description="Summary relevant for the file")

    class Config:
        title = "FileDescription"


class GenerateFileSummaryOutput(BaseModel):
    """Collection of summaries, accessible by file path"""

    items: Dict[str, str] = Field(description="A dictionary of file-wise summary objects")

    class Config:
        title = "SolutionSummary"

    def describe_solution_summary(self) -> str:
        descriptions = []
        for file_path, file_summary in self.items.items():
            description = f"File {file_path}: {file_summary}"
            descriptions.append(description)
        return "\n".join(descriptions)
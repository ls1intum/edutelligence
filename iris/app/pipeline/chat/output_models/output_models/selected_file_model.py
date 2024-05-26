from typing import List

from pydantic.v1 import BaseModel as V1BaseModel, Field as V1Field


class SelectedFiles(V1BaseModel):
    selected_files: List[str] = V1Field(
        description="List of selected files from the repository. Minimum 0 files, maximum 5 files."
    )

from typing import List

from pydantic.v1 import BaseModel as V1BaseModel, Field as V1Field


class SelectedFiles(V1BaseModel):
    selected_files: List[str] = V1Field(
        description="List of selected files from the repository based on chat history and build_logs,this field is "
        "set as an empty list if no files are selected"
    )

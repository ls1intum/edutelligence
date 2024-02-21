from pydantic.v1 import BaseModel as V1BaseModel, Field as V1Field


class SelectedFile(V1BaseModel):
    selected_file: str = V1Field(
        description="The selected file that is necessary for the exercise, otherwise empty"
    )

from pydantic import BaseModel, Field

class Submission(BaseModel):
    id: int = Field(example=1)
    score_in_points: float = Field(example=1.0)
    participation_id: int = Field(example=1)
    file_path: str = Field(example="exercise_1/solution.py")
    text: str = Field(example="print('Hello World!')")
    language: str = Field(example="python")
    meta: dict = Field(example={})

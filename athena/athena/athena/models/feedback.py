from pydantic import BaseModel, Field

class Feedback(BaseModel):
    id: int = Field(example=1)
    exercise_id: int = Field(example=1)
    submission_id: int = Field(example=1)
    detail_text: str = Field(example="Your solution is correct.")
    text: str = Field(example="Correct")
    type: str = Field(example="success")
    credits: float = Field(example=1.0)

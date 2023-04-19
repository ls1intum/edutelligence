from pydantic import BaseModel, Field

class Submission(BaseModel):
    id: int = Field(example=1)
    exercise_id: int = Field(example=1)
    content: str = Field(example="https://lms.example.com/assignments/1/submissions/1/download")
    student_id: int = Field(example=1)
    meta: dict = Field(example={})

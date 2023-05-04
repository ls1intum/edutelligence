import abc

from pydantic import BaseModel, Field

from .exercise_type import ExerciseType
# from athena.storage.models.exercise import DBExercise


class Exercise(BaseModel, abc.ABC):
    """An exercise that can be solved by students, enhanced with metadata depending on its type."""
    id: int = Field(example=1)
    title: str = Field(description="The title of the exercise.", 
                       example="Exercise 1")
    type: ExerciseType = Field(example=ExerciseType.text)
    max_points: float = Field(ge=0, 
                              description="The maximum number of points that can be achieved.", 
                              example=1.0)
    bonus_points: float = Field(ge=0, 
                                description="The number of bonus points that can be achieved.", 
                                example=0.0)
    grading_instructions: str = Field(description="Markdown text that describes how the exercise is graded.", 
                                      example="Give 1 point for each correct answer.")
    problem_statement: str = Field(description="Markdown text that describes the problem statement.",
                                   example="Write a program that prints 'Hello World!'")

    meta: dict = Field(example={"internal_id": "5"})

    @abc.abstractmethod
    def to_db_model(self):# -> DBExercise: # TODO: add type again here
        ...

    class Config:
        orm_mode = True

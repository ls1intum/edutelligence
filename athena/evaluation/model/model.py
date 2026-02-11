from dataclasses import dataclass, asdict
from typing import Optional, List, Union, Dict


@dataclass
class Feedback:
    id: Optional[int]
    title: Optional[str]
    description: Optional[str]
    credits: float
    index_start: Optional[int]
    index_end: Optional[int]
    structured_grading_instruction_id: Optional[int]
    meta: dict
    exercise_id: int
    submission_id: int
    type: str

    def __init__(
        self,
        id: Optional[int],
        title: Optional[str],
        description: Optional[str],
        credits: float,
        index_start: Optional[int],
        index_end: Optional[int],
        structured_grading_instruction_id: Optional[int],
        exercise_id: int,
        submission_id: int,
    ) -> None:
        self.id = id if id is None else int(id)
        self.title = title
        self.description = description
        self.credits = float(credits)
        self.index_start = index_start if index_start is None else int(index_start)
        self.index_end = index_end if index_end is None else int(index_end)
        self.structured_grading_instruction_id = (
            structured_grading_instruction_id
            if structured_grading_instruction_id is None
            else int(structured_grading_instruction_id)
        )
        self.meta = {}
        self.exercise_id = int(exercise_id)
        self.submission_id = int(submission_id)
        self.type = "text"


@dataclass
class Submission:
    id: int
    text: str
    language: str
    meta: dict
    feedbacks: Optional[Union[List[Feedback], Dict[str, List[Feedback]]]] = None

    def __init__(
        self,
        id: int,
        text: str,
        language: str,
        feedbacks: Optional[Union[List[Feedback], Dict[str, List[Feedback]]]],
        meta: Optional[dict] = None,
    ) -> None:
        self.id = int(id)
        self.text = text
        self.language = language
        self.meta = {} if meta is None else dict(meta)
        self.feedbacks = feedbacks


@dataclass
class StructuredGradingInstruction:
    id: int
    credits: float
    grading_scale: str
    instruction_description: str
    feedback: str
    usage_count: int

    def __init__(
        self,
        id: int,
        credits: float,
        grading_scale: str,
        instruction_description: str,
        feedback: str,
        usage_count: int,
    ) -> None:
        self.id = int(id)
        self.credits = float(credits)
        self.grading_scale = grading_scale
        self.instruction_description = instruction_description
        self.feedback = feedback
        self.usage_count = int(usage_count)


@dataclass
class GradingCriterion:
    id: int
    title: Optional[str]
    structured_grading_instructions: List[StructuredGradingInstruction]

    def __init__(
        self,
        id: int,
        title: str,
        structured_grading_instructions: List[StructuredGradingInstruction],
    ) -> None:
        self.id = int(id)
        self.title = title
        self.structured_grading_instructions = structured_grading_instructions


@dataclass
class Exercise:
    id: int
    title: str
    type: str
    max_points: float
    bonus_points: float
    grading_instructions: Optional[str]
    grading_criteria: Optional[List[GradingCriterion]]
    problem_statement: Optional[str]
    meta: dict
    example_solution: Optional[str]
    submissions: List[Submission]

    def __init__(
        self,
        id: int,
        title: str,
        max_points: float,
        bonus_points: float,
        grading_instructions: str,
        grading_criteria: List[GradingCriterion],
        problem_statement: str,
        example_solution: str,
        submissions: List[Submission],
        type: str = "text",
        meta: Optional[dict] = None,
    ) -> None:
        self.id = int(id)
        self.title = title
        self.type = type
        self.max_points = float(max_points)
        self.bonus_points = float(bonus_points)
        self.grading_instructions = grading_instructions
        self.grading_criteria = grading_criteria
        self.problem_statement = problem_statement
        self.meta = {} if meta is None else dict(meta)
        self.example_solution = example_solution
        self.submissions = submissions

    def __str__(self):
        return f"Exercise({self.id}, {self.title}, {self.max_points}, {self.bonus_points}, {self.grading_instructions}, {self.grading_criteria}, {self.problem_statement}, {self.example_solution}, {self.submissions})"

    def to_dict(self):
        return asdict(self)

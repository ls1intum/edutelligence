from dataclasses import dataclass

@dataclass
class Exercise:
    id: int
    title: str
    max_points: float
    problem_statement: str
    example_solution: str
    package_name: str
    programming_language: str
    student_id: int
    meta: dict
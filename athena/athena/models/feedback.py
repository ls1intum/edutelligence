from dataclasses import dataclass

@dataclass
class Feedback:
    id: int
    exercise_id: int
    detail_text: str
    text: str
    type: str
    credits: float
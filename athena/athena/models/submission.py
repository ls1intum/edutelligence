from dataclasses import dataclass

@dataclass
class Submission:
    id: int
    score_in_points: float
    participation_id: int
    file_path: str
    text: str
    language: str
    meta: dict
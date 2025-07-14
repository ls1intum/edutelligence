import pytest
import logging
from typing import Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class MockExercise:
    
    id: int
    type: str = "programming"
    problem_statement: str = "Test problem statement"
    grading_instructions: str = "Test grading instructions"
    max_points: float = 10.0
    programming_language: str = "python"
    template_repository_uri: str = "http://mock/template"
    solution_repository_uri: str = "http://mock/solution"
    tests_repository_uri: str = "http://mock/tests"

    def get_template_repository(self):        
        return None

    def get_solution_repository(self):        
        return None

@dataclass
class MockSubmission:
    
    id: int
    exercise_id: int
    repository_uri: str
    files: Dict[str, str]

    def get_repository(self):        
        return None

@pytest.fixture
def mock_exercise():
    
    return MockExercise(id=1)

@pytest.fixture
def mock_submission():

    return MockSubmission(
        id=1,
        exercise_id=1,
        repository_uri="http://mock/submission",
        files={
            "test.py": "def test():\n    pass"
        }
    )

@pytest.fixture
def mock_empty_submission():
    
    return MockSubmission(
        id=2,
        exercise_id=1,
        repository_uri="http://mock/empty",
        files={}
    )
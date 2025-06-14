from typing import List, Optional, Dict, Any, Type
from pydantic import BaseModel
import asyncio
from unittest.mock import AsyncMock

class MockLanguageModel:
    
    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self.responses = responses or {}

    async def predict(self, messages: List[Dict[str, str]], **kwargs) -> str:
        system_message = next((msg["content"] for msg in messages if msg["role"] == "system"), "")
        
        if "Create graded feedback" in system_message:
            return """{"type": "Assessment", "title": "Logic Error", "description": "Doc important", "file_path": "test.py", "line_start": 1, "line_end": 1, "credits": 0.5}"""
        elif "Create non graded improvement suggestions" in system_message:
            return """{"type": "Improvement", "title": "Logic Error", "description": "Doc important", "file_path": "test.py", "line_start": 1, "line_end": 1}"""
        
        return """{"type": "Assessment", "title": "Logic Error", "description": "Doc important", "file_path": "test.py", "line_start": 1, "line_end": 1, "credits": 0.5}"""

async def mock_predict(messages: List[Dict[str, str]], **kwargs) -> str:
    loop = asyncio.get_event_loop()
    model = MockLanguageModel()
    return await loop.run_in_executor(None, lambda: model.predict(messages, **kwargs))

class MockAssessmentModel:
    
    def __init__(self):
        self.assess = AsyncMock()
        self.assess.return_value = {
            "score": 0.8,
            "feedback": "Mock feedback with detailed assessment",
            "details": {
                "code_quality": 0.9,
                "correctness": 0.7,
                "documentation": 0.8
            }
        }

def get_mock_response_for_model(model_type: Type[BaseModel]) -> Dict[str, Any]:
    if model_type.__name__ == "AssessmentModel":
        return {
            "feedbacks": [
                {
                    "title": "Test Feedback",
                    "description": "This is a test feedback with detailed explanation",
                    "line_start": 1,
                    "line_end": 2,
                    "credits": 1.0,
                    "grading_instruction_id": 1
                }
            ]
        }
    elif model_type.__name__ == "ImprovementModel":
        return {
            "feedbacks": [
                {
                    "title": "Improvement Suggestion",
                    "description": "This is a test improvement suggestion",
                    "line_start": 1,
                    "line_end": 2
                }
            ]
        }
    return {}

async def mock_predict_and_parse(pydantic_object: Optional[Type[BaseModel]] = None):
    async def mock_predict(*args, **kwargs):
        if pydantic_object is None:
            return None
        mock_data = get_mock_response_for_model(pydantic_object)
        if not mock_data:
            return None
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: pydantic_object(**mock_data)
        )
    return mock_predict
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
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

class MockAssessmentModel(BaseModel):
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
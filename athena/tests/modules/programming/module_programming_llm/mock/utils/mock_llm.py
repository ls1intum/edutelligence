from typing import List, Optional, Dict, Any
from pydantic import ConfigDict, BaseModel, Field
from unittest.mock import AsyncMock

class MockLanguageModel:
    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        # Map system-prompt → mocked model payload (dict / serialisable)
        self.responses: Dict[str, Any] = responses or {}

    async def predict(self, messages: List[Dict[str, str]], **kwargs) -> Any:  
        system_message = next((msg["content"] for msg in messages if msg["role"] == "system"), "")
        
        if system_message in self.responses:
            return self.responses[system_message]  
        elif "Create graded feedback" in system_message:
            return {
                "type": "Assessment", 
                "title": "Logic Error", 
                "description": "Doc important", 
                "file_path": "test.py", "line_start": 1, 
                "line_end": 1, "credits": 0.5
                }
        elif "Create non graded improvement suggestions" in system_message:
            return {
                "type": "Improvement", 
                "title": "Logic Error", 
                "description": "Doc important", 
                "file_path": "test.py", 
                "line_start": 1, 
                "line_end": 1}
        
        return {
            "type": "Assessment",
            "title": "Logic Error",
            "description": "Doc important",
            "file_path": "test.py",
            "line_start": 1,
            "line_end": 1,
            "credits": 0.5
                }

class MockAssessmentModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    assess: AsyncMock = Field(default_factory=lambda: AsyncMock(
        return_value={
            "score": 0.8,
            "feedback": "Mock feedback with detailed assessment",
            "details": {
                "code_quality": 0.9,
                "correctness": 0.7,
                "documentation": 0.8,
            },
        }
    ))
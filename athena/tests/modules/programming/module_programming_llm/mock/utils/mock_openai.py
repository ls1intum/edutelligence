import sys
from unittest.mock import Mock, patch
from typing import Any, Dict
import json

# Create mock objects that can be used in fixtures instead of globally overwriting sys.modules
def create_mock_openai_module():
    """Create a mock OpenAI module for use in fixtures."""
    mock_openai = Mock()
    mock_openai.OpenAIModelConfig = Mock
    mock_openai.available_models = {'mock_model': Mock()}
    return mock_openai

def create_mock_openai_client():
    """Create a mock OpenAI client for use in fixtures."""
    mock_openai_client = Mock()
    mock_openai_client.models.list.return_value = []
    return mock_openai_client

def get_tool_name_from_system_message(system_message: str) -> str:
    
    if "Create non graded improvement suggestions" in system_message:
        return "ImprovementModel"
    elif "Create graded feedback" in system_message:
        return "Assessment"
    return "Assessment"  # Default to Assessment

class MockChatCompletion:
    
    def __init__(self, tool_name: str = "Assessment"):
        self.id = "mock-chat-completion"
        self.choices = [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_mock",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps({
                            "feedbacks": [{
                                "title": "Logic Error",
                                "description": "Doc important",
                                "line_start": 1,
                                "line_end": 1,
                                "credits": 0.5 if tool_name == "Assessment" else None
                            }]
                        })
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }]
        self.usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "choices": self.choices,
            "usage": self.usage
        }

async def mock_create(*args, **kwargs) -> MockChatCompletion:
    messages = kwargs.get("messages", [])
    system_message = next((msg["content"] for msg in messages if msg["role"] == "system"), "")
    tool_name = get_tool_name_from_system_message(system_message)
    return MockChatCompletion(tool_name=tool_name)

class MockClient:
    
    def __init__(self):
        self.chat = Mock()
        self.chat.completions.create = mock_create

class MockAsyncClient:
    
    def __init__(self):
        self.chat = Mock()
        self.chat.completions.create = mock_create

# Apply the patches
patch("openai.OpenAI", return_value=MockClient()).start()
patch("openai.AsyncAzureOpenAI", return_value=MockAsyncClient()).start()

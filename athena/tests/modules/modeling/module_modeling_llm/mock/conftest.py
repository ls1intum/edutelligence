import pytest
import json
from pydantic import ConfigDict, Field
from unittest.mock import patch
from typing import Any, Dict, List, Optional, Type
from athena.modeling import Exercise, Submission
from athena.schemas import ExerciseType
from athena.module_config import ModuleConfig
from module_modeling_llm.config import Configuration, BasicApproachConfig
from langchain_community.chat_models.fake import FakeListChatModel
from langchain_core.pydantic_v1 import BaseModel
from llm_core.models.providers.openai_model_config import OpenAIModelConfig


class FakeChatModel(FakeListChatModel):
    """A fake chat model for testing purposes"""

    requests: List[Dict] = Field(default_factory=list)
    responses: List[Any] = Field(default_factory=list)
    pydantic_object: Optional[Type[BaseModel]] = None

    def get_model(self):
        return self


class FakeModelConfig(OpenAIModelConfig):
    """A fake ModelConfig that extends OpenAIModelConfig for testing"""

    model_name: str = "fake_model"

    def get_model(self, openai_catalog=None):
        """Override to return our fake model"""
        return FakeChatModel()

    model_config = ConfigDict(arbitrary_types_allowed=True)


stub = ModuleConfig(name="module_modeling_llm", type=ExerciseType.modeling, port=5001)
patch("athena.module_config.get_module_config", return_value=stub).start()


@pytest.fixture
def mock_exercise():
    """Create a mock exercise for testing"""
    example_solution = {
        "type": "class",
        "elements": {
            "1": {"id": "1", "type": "class", "name": "User", "attributes": ["2", "3"]},
            "2": {"id": "2", "type": "attribute", "name": "name"},
            "3": {"id": "3", "type": "attribute", "name": "password"},
            "4": {
                "id": "4",
                "type": "class",
                "name": "Order",
                "attributes": ["5", "6"],
            },
            "5": {"id": "5", "type": "attribute", "name": "orderId"},
            "6": {"id": "6", "type": "attribute", "name": "date"},
        },
        "relationships": {
            "1": {
                "id": "1",
                "type": "association",
                "source": {"element": "1"},
                "target": {"element": "4"},
            }
        },
    }
    return Exercise(
        id=1,
        title="Test Exercise",
        type=ExerciseType.modeling,
        max_points=10,
        bonus_points=0,
        grading_instructions="Grade this diagram.",
        problem_statement="Model a user and an order.",
        example_solution=json.dumps(example_solution),
        grading_criteria=[],
        meta={},
    )


@pytest.fixture
def mock_submission(mock_exercise):
    """Create a mock submission for testing"""
    model_data = {
        "type": "class",
        "elements": {
            "1": {"id": "1", "type": "class", "name": "User", "attributes": ["2", "3"]},
            "2": {"id": "2", "type": "attribute", "name": "name"},
            "3": {"id": "3", "type": "attribute", "name": "password"},
            "4": {
                "id": "4",
                "type": "class",
                "name": "Order",
                "attributes": ["5", "6"],
            },
            "5": {"id": "5", "type": "attribute", "name": "orderId"},
            "6": {"id": "6", "type": "attribute", "name": "date"},
        },
        "relationships": {
            "1": {
                "id": "1",
                "type": "association",
                "source": {"element": "1"},
                "target": {"element": "4"},
            }
        },
    }
    return Submission(
        id=1, exercise_id=mock_exercise.id, model=json.dumps(model_data), meta={}
    )


@pytest.fixture
def mock_config():
    """
    Provides a mock configuration object for the modeling module.
    This replaces the need for patching global config loaders.
    """
    fake_model_config = FakeModelConfig(
        model_name="fake_model",
        provider="openai",
        max_tokens=4000,
        temperature=0.0,
        top_p=1.0,
        presence_penalty=0.0,
        frequency_penalty=0.0,
    )

    approach = BasicApproachConfig(
        generate_feedback=fake_model_config,
        filter_feedback=fake_model_config,
        review_feedback=fake_model_config,
        generate_grading_instructions=fake_model_config,
    )
    return Configuration(debug=True, approach=approach)

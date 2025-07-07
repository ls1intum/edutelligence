import pytest
import json
from pydantic import dataclasses
from unittest.mock import patch
from athena.module_config import ModuleConfig
from athena.schemas.exercise_type import ExerciseType

patcher = patch(
    "athena.module_config.get_module_config",
    return_value=ModuleConfig(
        name="module_modeling_llm", type=ExerciseType.modeling, port=5008
    ),
)
patcher.start()

from athena.modeling import Exercise, Submission
from athena.schemas.exercise_type import ExerciseType
from athena.schemas.structured_grading_criterion import StructuredGradingCriterion

from module_modeling_llm.config import (
    BasicApproachConfig,
    Configuration,
    GenerateSuggestionsPrompt,
)
from utils.fake_llm import FakeChatModel, FakeModelConfig
from unittest.mock import patch
from athena.module_config import ModuleConfig


@dataclasses.dataclass
class TestData:
    exercise: Exercise
    submission: Submission
    structured_grading_instructions: StructuredGradingCriterion


@pytest.fixture(autouse=True)
def mock_athena_module_config():
    """
    Automatically mocks get_module_config for all tests in this directory.
    This prevents the tests from trying to read a 'module.conf' file from the filesystem.
    """
    # This is the configuration that 'module_modeling_llm' would have at runtime.
    mock_config = ModuleConfig(
        name="module_modeling_llm", type=ExerciseType.modeling, port=5008
    )
    with patch(
        "athena.module_config.get_module_config", return_value=mock_config
    ) as mock:
        yield mock


@pytest.fixture
def test_data() -> TestData:
    """Provides a standard set of exercise and submission data for tests."""
    exercise = Exercise(
        id=1,
        title="Test Exercise",
        type=ExerciseType.modeling,
        max_points=10,
        problem_statement="Create a class diagram with User and Order.",
        grading_instructions="User must have name. Order must exist.",
        grading_criteria=[],
        example_solution=json.dumps(
            {"type": "ClassDiagram", "elements": {}, "relationships": {}}
        ),
        meta={},
        bonus_points=0,
    )
    submission = Submission(
        id=1,
        exercise_id=exercise.id,
        model=json.dumps(
            {
                "type": "ClassDiagram",
                "elements": {"1": {"id": "1", "type": "Class", "name": "User"}},
                "relationships": {},
            }
        ),
        meta={},
    )
    sgi = StructuredGradingCriterion(criteria=[])

    return TestData(
        exercise=exercise, submission=submission, structured_grading_instructions=sgi
    )


@dataclasses.dataclass
class TestEnvironment:
    config: Configuration
    fake_model: FakeChatModel


@pytest.fixture
def test_env() -> TestEnvironment:
    """
    Sets up a complete and isolated test environment using the Fake LLM.
    This replaces all the complex patching and mocking.
    """
    # 1. Create the fake LLM instance that we can control
    fake_chat_model = FakeChatModel()

    # 2. Create the fake model config, injecting our fake LLM and setting capabilities.
    # The `BadRequestError` showed the real 'o1-mini' model was called, which
    # doesn't support system messages. We set this capability to False to ensure
    # the code under test (which should remove system messages) is triggered correctly.
    fake_model_config = FakeModelConfig(
        _fake_chat_model=fake_chat_model,
        _capability_system_messages=False,
        _capability_function_calling=False,
        _capability_structured_output=False,
    )

    # 3. Create the actual module configuration, injecting the fake config.
    # This works because FakeModelConfig is a subclass of OpenAIModelConfig,
    # so Pydantic validation passes without coercing it to a new object.
    module_config = Configuration(
        debug=True,
        approach=BasicApproachConfig(
            generate_feedback=fake_model_config,
            filter_feedback=fake_model_config,
            review_feedback=fake_model_config,
            generate_grading_instructions=fake_model_config,
            # Prompts can be left as default or customized here
            generate_suggestions_prompt=GenerateSuggestionsPrompt(),
        ),
    )

    return TestEnvironment(config=module_config, fake_model=fake_chat_model)

from unittest.mock import patch
from athena.module_config import ModuleConfig
from athena.schemas.exercise_type import ExerciseType

mock_config = ModuleConfig(
    name="module_programming_llm",
    type=ExerciseType.programming,
    port=5002
)

# Apply the patch before any other imports
patch("athena.module_config.get_module_config", return_value=mock_config).start() 
import sys

from llm_core.models.mock_llm import FakeLLM

ModelConfigType = FakeLLM
DefaultModelConfig = FakeLLM
evaluation_model = FakeLLM

sys.path = [p for p in sys.path if 'integration_tests' not in p]
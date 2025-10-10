from pydantic import BaseModel, Field

from athena.schemas import LearnerProfile
from module_text_llm.approach_config import ApproachConfig


class MockPrompt(BaseModel):
    """Mock prompt template with system and human messages."""

    system_message: str = "Test system message"
    human_message: str = "Test human message"


class MockApproachConfig(ApproachConfig):
    """Mock approach configuration for testing."""

    generate_suggestions_prompt: MockPrompt = Field(default_factory=MockPrompt)
    analyze_submission_prompt: MockPrompt = Field(default_factory=MockPrompt)
    learner_profile: LearnerProfile = Field(default_factory=lambda: LearnerProfile(
        feedback_detail=2,
        feedback_formality=2,
    ))

    async def generate_suggestions(
        self, exercise, submission, debug=False, is_graded=True
    ):
        """Mock implementation of generate_suggestions."""
        return []

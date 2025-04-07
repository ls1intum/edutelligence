from typing import Annotated

from pydantic import BaseModel, Field


class LearnerProfile(BaseModel):
    """
    Model representing learner profile.

    Each preference is on a scale from 1 to 5, where:
    - 1 represents one extreme (e.g., very practical)
    - 5 represents the opposite extreme (e.g., very theoretical)
    """

    practical_theoretical: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for practical (1) vs theoretical (5) feedback."
    )]
    creative_guidance: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for creative exploration (1) vs focused guidance (5)."
    )]
    followup_summary: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for follow-up questions (1) vs summary/conclusion (5)."
    )]
    brief_detailed: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for brief (1) vs detailed (5) feedback."
    )]

    def describe_practical_theoretical(self) -> str:
        mapping = {
            1: "Strong preference for hands-on, example-driven feedback grounded in real-world use cases.",
            2: "Leans toward practical applications with occasional theoretical support.",
            3: "Balanced between practical examples and conceptual explanations.",
            4: "Leans toward conceptual clarity, including definitions and abstract reasoning.",
            5: "Strong preference for theoretical insight and abstract conceptual understanding."
        }
        return mapping[self.practical_theoretical]

    def describe_creative_guidance(self) -> str:
        mapping = {
            1: "Strong preference for creative prompts, encouragement to explore alternative approaches or perspectives.",
            2: "Enjoys occasional nudges to think divergently or apply different methods.",
            3: "Open to both creative thinking and structured guidance.",
            4: "Appreciates direct guidance and step-by-step reasoning over divergent prompts.",
            5: "Strong preference for focused, structured explanations with minimal deviation from core reasoning."
        }
        return mapping[self.creative_guidance]

    def describe_followup_summary(self) -> str:
        mapping = {
            1: "Strong preference for engaging follow-up questions that provoke reflection and deeper thinking.",
            2: "Enjoys occasional follow-up prompts to extend learning.",
            3: "Open to both follow-up questions and summary-style conclusions.",
            4: "Prefers feedback to conclude with a clear summary rather than additional questions.",
            5: "Strong preference for concise takeaways and wrap-up conclusions without further prompting."
        }
        return mapping[self.followup_summary]

    def describe_brief_detailed(self) -> str:
        mapping = {
            1: "Strong preference for concise, no-frills feedback with minimal elaboration.",
            2: "Prefers mostly brief feedback with occasional explanation.",
            3: "Comfortable with moderately detailed feedback—clear, but not overwhelming.",
            4: "Prefers thorough, context-rich feedback with elaborated reasoning.",
            5: "Strong preference for highly detailed explanations, background context, and comprehensive coverage."
        }
        return mapping[self.brief_detailed]

    def to_feedback_style_description(self) -> str:
        return (
            f"- {self.describe_practical_theoretical()}\n"
            f"- {self.describe_creative_guidance()}\n"
            f"- {self.describe_followup_summary()}\n"
            f"- {self.describe_brief_detailed()}"
        )

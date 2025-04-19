from typing import Annotated

from pydantic import BaseModel, Field

class LearnerProfile(BaseModel):
    """
    Model representing learner profile.

    Each preference is on a scale from 1 to 5, where:
    - 1 represents one extreme (e.g., very practical)
    - 5 represents the opposite extreme (e.g., very theoretical)
    """

    feedback_practical_theoretical: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for practical (1) vs theoretical (5) feedback."
    )]
    feedback_creative_guidance: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for creative exploration (1) vs focused guidance (5)."
    )]
    feedback_followup_summary: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for follow-up questions (1) vs summary/conclusion (5)."
    )]
    feedback_brief_detailed: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for brief (1) vs detailed (5) feedback."
    )]

    def describe_practical_theoretical(self) -> str:
        mapping = {
            1: "Prefers feedback grounded in real-world programming scenarios, hands-on examples, and direct application of concepts.",
            2: "Likes feedback with concrete examples, supported by light theoretical reasoning.",
            3: "Appreciates a mix of practical usage and abstract understanding.",
            4: "Prefers conceptual clarity and deeper reasoning over concrete examples.",
            5: "Values theoretical insights, abstract patterns, and high-level generalizations over practical details."
        }
        return mapping[self.feedback_practical_theoretical]

    def describe_creative_guidance(self) -> str:
        mapping = {
            1: "Enjoys speculative prompts and encouragement to try new or unconventional approaches.",
            2: "Appreciates occasional nudges to explore alternative methods or think differently.",
            3: "Open to both creative exploration and structured guidance.",
            4: "Prefers structured reasoning and step-by-step guidance over creative detours.",
            5: "Strong preference for direct, focused problem-solving with minimal deviation from known solutions."
        }
        return mapping[self.feedback_creative_guidance]

    def describe_followup_summary(self) -> str:
        mapping = {
            1: "Values open-ended follow-up questions that invite reflection and critical thinking.",
            2: "Likes occasional follow-up prompts to deepen understanding.",
            3: "Comfortable with both reflective questions and summary-style conclusions.",
            4: "Prefers feedback to conclude with a clear takeaway, rather than additional questions.",
            5: "Strong preference for concise summaries and clear conclusions without further prompting."
        }
        return mapping[self.feedback_followup_summary]

    def describe_brief_detailed(self) -> str:
        mapping = {
            1: "Wants short, direct feedback with minimal elaboration — 1–2 sentence max.",
            2: "Prefers brief feedback with occasional clarifying details.",
            3: "Comfortable with moderately detailed feedback — clear, but not too lengthy.",
            4: "Likes context-rich explanations, including rationale or mini-examples.",
            5: "Expects thorough, multi-sentence feedback with comprehensive reasoning and background."
        }
        return mapping[self.feedback_brief_detailed]

    def to_feedback_style_description(self) -> str:
        return (
            f"- {self.describe_practical_theoretical()}\n"
            f"- {self.describe_creative_guidance()}\n"
            f"- {self.describe_followup_summary()}\n"
            f"- {self.describe_brief_detailed()}"
        )

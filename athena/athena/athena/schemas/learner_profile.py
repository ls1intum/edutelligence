from typing import Annotated

from pydantic import BaseModel, Field

class LearnerProfile(BaseModel):
    """
    Model representing learner profile.

    Each preference is on a scale from 1 to 3, where:
    - 1 represents one extreme (e.g., brief or friendly)
    - 3 represents the opposite extreme (e.g., detailed or formal)
    - 2 represents the neutral case - no influence on the generation
    """
    feedback_detail: Annotated[int, Field(
        strict=True, ge=1, le=3,
        description="Preference for brief (1) vs detailed (3) feedback.."
    )]
    feedback_formality: Annotated[int, Field(
        strict=True,
        description="Preference for friendly (1) vs formal (3) feedback."
    )]
    class Config:
        @staticmethod
        def alias_generator(s: str) -> str:
            return ''.join([s.split('_')[0]] + [word.capitalize() for word in s.split('_')[1:]])
        allow_population_by_field_name = True

    def _get_feedback_detail_prompt(self) -> str:
        if self.feedback_detail == 1:
            return (
                "Keep the feedback short and direct — ideally 1 to 2 sentences.\n"
                "Example 1: Add an index on the user_id column to improve performance.\n"
                "Example 2: Clarify your thesis statement in the introduction to strengthen your argument.\n"
            )
        if self.feedback_detail == 3:
            return (
                "Give detailed feedback with multiple sentences, examples, and background reasoning where relevant.\n"
                "Example 1: Adding an index on user_id improves query speed by allowing the database to locate relevant rows efficiently without scanning the entire table, which is crucial for scaling.\n"
                "Example 2: Introducing your main argument clearly in the essay's opening not only frames the reader's expectations but also strengthens your persuasiveness, a technique often recommended in academic writing.\n"
                )
        return ""

    def _get_feedback_formality_prompt(self) -> str:
        if self.feedback_formality == 1:
            return (
                "Provide feedback in a friendly and engaging tone, like a tutor would. Use emojis to make the feedback more engaging 👍👉🙌🚀🎯✏️➡️. Motivate the learner to improve.\n"
                "Example 1: 💪 Let's boost your query performance by adding an index on the user_id column! 🚀\n"
                "Example 2: 👉 Introducing your main argument clearly in the essay's opening not only frames the reader's expectations but also strengthens your persuasiveness, a technique often recommended in academic writing. 📚\n"
            )
        if self.feedback_formality == 3:
            return (
                "Provide feedback in a formal and professional tone, like a teacher would, keep the neutral tone.\n"
                "Example 1: Add an index on the user_id column to improve performance.\n"
                "Example 2: Clarify your thesis statement in the introduction to strengthen your argument.\n"
            )
        return ""

    def get_prompt(self) -> str:
        guideline = "Generate feedback according to the following instructions:\n" if self.feedback_detail != 2 and self.feedback_formality != 2 else ""
        return (
            f"{guideline}"
            f"1. {self._get_feedback_detail_prompt()}\n"
            f"2. {self._get_feedback_formality_prompt()}\n"
        )

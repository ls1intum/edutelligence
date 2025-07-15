from typing import Annotated

from pydantic import BaseModel, Field

class LearnerProfile(BaseModel):
    """
    Model representing learner profile.

    Each preference is boolean.
    - is_brief_feedback: True if the learner prefers brief feedback, False if they prefer detailed feedback.
    - is_formal_feedback: True if the learner prefers formal feedback, False if they prefer friendly feedback.
    """
    is_brief_feedback: Annotated[bool, Field(
        strict=True,
        description="Preference for brief vs detailed feedback."
    )]
    is_formal_feedback: Annotated[bool, Field(
        strict=True,
        description="Preference for formal vs friendly feedback."
    )]
    class Config:
        @staticmethod
        def alias_generator(s: str) -> str:
            return ''.join([s.split('_')[0]] + [word.capitalize() for word in s.split('_')[1:]])
        allow_population_by_field_name = True

    def directive_brief_detailed(self) -> str:
        if self.is_brief_feedback:
            return (
                "Keep the feedback short and direct — ideally 1 to 2 sentences.\n"
                "Example 1: Add an index on the user_id column to improve performance.\n"
                "Example 2: Clarify your thesis statement in the introduction to strengthen your argument.\n"
            )
        return (
            "Give detailed feedback with multiple sentences, examples, and background reasoning where relevant.\n"
            "Example 1: Adding an index on user_id improves query speed by allowing the database to locate relevant rows efficiently without scanning the entire table, which is crucial for scaling.\n"
            "Example 2: Introducing your main argument clearly in the essay's opening not only frames the reader's expectations but also strengthens your persuasiveness, a technique often recommended in academic writing.\n"
            )

    def directive_formal_friendly(self) -> str:
        if self.is_formal_feedback:
            return (
                "Provide feedback in a formal and professional tone, like a teacher would, keep the neutral tone.\n"
                "Example 1: Add an index on the user_id column to improve performance.\n"
                "Example 2: Clarify your thesis statement in the introduction to strengthen your argument.\n"
            )
        return (
            "Provide feedback in a friendly and engaging tone, like a tutor would. Use emojis to make the feedback more engaging 👍👉🙌🚀🎯✏️➡️. Motivate the learner to improve.\n"
            "Example 1: 💪 Let's boost your query performance by adding an index on the user_id column! 🚀\n"
            "Example 2: 👉 Introducing your main argument clearly in the essay's opening not only frames the reader's expectations but also strengthens your persuasiveness, a technique often recommended in academic writing. 📚\n"
        )

    def to_feedback_style_description(self) -> str:
        return (
            f"Generate feedback according to the following instructions:\n"
            f"1. {self.directive_brief_detailed()}\n"
            f"2. {self.directive_formal_friendly()}\n"
        )

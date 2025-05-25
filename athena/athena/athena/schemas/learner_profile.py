from typing import Annotated

from pydantic import BaseModel, Field

class LearnerProfile(BaseModel):
    """
    Model representing learner profile.

    Each preference is on a scale from 1 to 3, where:
    - 1 represents one extreme (e.g., focus on suggesting alternative solutions)
    - 3 represents the opposite extreme (e.g., focus on the standards)
    """
    feedback_alternative_standard: Annotated[int, Field(
        strict=True, ge=1, le=3,
        description="Preference for creative exploration and alternatives (1) vs de-facto standards (3)."
    )]
    feedback_followup_summary: Annotated[int, Field(
        strict=True, ge=1, le=3,
        description="Preference for follow-up questions (1) vs summary/conclusion (3)."
    )]
    feedback_brief_detailed: Annotated[int, Field(
        strict=True, ge=1, le=3,
        description="Preference for brief (1) vs detailed (3) feedback."
    )]

    class Config:
        alias_generator = lambda s: ''.join([s.split('_')[0]] + [word.capitalize() for word in s.split('_')[1:]])
        allow_population_by_field_name = True

    def directive_alternative_standard(self) -> str:
        if self.feedback_alternative_standard == 1:
            return (
                "Encourage exploration by suggesting alternative approaches or creative methods.\n"
                "Example 1: Besides QuickSort, you could also explore MergeSort or InsertionSort depending on the dataset characteristics.\n"
                "Example 2: Instead of writing a formal essay, you could experiment with a narrative storytelling approach to engage the reader differently.\n"
            )
        if self.feedback_alternative_standard == 2:
            return (
                "Present the standard solution clearly, but briefly mention one alternative approach.\n"
                "Example 1: QuickSort is efficient for large datasets, but for nearly sorted data, InsertionSort could be faster.\n"
                "Example 2: While a chronological structure works well for essays, you might briefly consider using a thematic structure.\n"
            )
        return (
            "Focus strictly on the most conventional, best-practice solution.\n"
            "Avoid suggesting alternatives unless necessary.\n"
            "Example 1: Use QuickSort for efficient large dataset sorting as it is widely considered the best practical choice.\n"
            "Example 2: Structure your essay with a clear introduction, body paragraphs supporting a single thesis, and a conclusion as per academic writing standards.\n"
        )

    def directive_followup_summary(self) -> str:
        if self.feedback_followup_summary <= 2:
            return (
                "End the feedback with a clear, specific follow-up question that promotes reflection.\n"
                "- If the answer is partially incorrect: Ask a focused question that hints at the mistake without giving away the solution.\n"
                "- If the answer is correct: Ask a question to deepen understanding or extend the concept.\n"
                "Examples:\n"
                "  - What might change if you had multiple tables related to 'users'?\n"
                "  - How would your solution scale if the dataset size doubled?\n"
                "Ensure questions are easy to understand and clearly direct what kind of reflection is expected.\n"
            )
        return (
            "End the feedback with a concise and clear summary.\n"
            "- Summarize the key point(s) of the feedback.\n"
            "- Avoid introducing open-ended questions unless necessary.\n"
            "Examples:\n"
            "  - In summary, using an index on user_id will optimize lookup performance.\n"
            "  - Overall, structuring your argument with clear topic sentences improves clarity.\n"
        )

    def directive_brief_detailed(self) -> str:
        if self.feedback_brief_detailed == 1:
            return (
                "Keep the feedback short and direct — ideally 1 to 2 sentences.\n"
                "Example 1: Add an index on the user_id column to improve performance.\n"
                "Example 2: Clarify your thesis statement in the introduction to strengthen your argument.\n"
            )
        if self.feedback_brief_detailed == 2:
            return (
                "Provide moderately detailed feedback, giving clear explanations without unnecessary length.\n"
                "Example 1: Consider indexing user_id to speed up lookups; it helps databases quickly find matching records\n."
                "Example 2: Starting your essay with a strong thesis helps guide the reader; this can also make your argumentation clearer.\nv"
            )
        return (
            "Give detailed feedback with multiple sentences, examples, and background reasoning where relevant.\n"
            "Example 1: Adding an index on user_id improves query speed by allowing the database to locate relevant rows efficiently without scanning the entire table, which is crucial for scaling.\n"
            "Example 2: Introducing your main argument clearly in the essay's opening not only frames the reader's expectations but also strengthens your persuasiveness, a technique often recommended in academic writing.\n"
            )

    def to_feedback_style_description(self) -> str:
        return (
            f"Please generate feedback according to the following instructions:\n"
            f"2. {self.directive_alternative_standard()}\n"
            f"3. {self.directive_followup_summary()}\n"
            f"4. {self.directive_brief_detailed()}\n"
        )

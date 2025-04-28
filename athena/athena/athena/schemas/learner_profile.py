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
    feedback_alternative_standard: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for creative exploration and alternatives (1) vs de-facto standards (5)."
    )]
    feedback_followup_summary: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for follow-up questions (1) vs summary/conclusion (5)."
    )]
    feedback_brief_detailed: Annotated[int, Field(
        strict=True, ge=1, le=5,
        description="Preference for brief (1) vs detailed (5) feedback."
    )]

    def directive_practical_theoretical(self) -> str:
        if self.feedback_practical_theoretical <= 2:
            return """
                Focus the feedback on real-world applications and practical usage.
                Example 1: To optimize database queries, you could add an index on the user_id column.
                Example 2: When organizing an event, you could start by booking the venue early to avoid last-minute issues.
                """
        elif self.feedback_practical_theoretical == 3:
            return """
                Balance practical examples with theoretical explanations.
                Example 1: Normalization reduces redundancy in databases; for instance, splitting user data into separate tables improves efficiency.
                Example 2: Effective time management involves prioritizing urgent tasks; for example, using the Eisenhower Matrix can help you decide quickly.
                """
        else:  # 4 or 5
            return """
                Focus the feedback on abstract principles and theoretical understanding.
                Example 1: In relational databases, normalization follows formal rules to reduce anomalies and ensure data integrity.
                Example 2: Time management theories suggest that cognitive load reduction improves long-term productivity, according to academic research.
                """

    def directive_alternative_standard(self) -> str:
        if self.feedback_alternative_standard <= 2:
            return """
                Encourage exploration by suggesting alternative approaches or creative methods.
                Example 1: Besides QuickSort, you could also explore MergeSort or InsertionSort depending on the dataset characteristics.
                Example 2: Instead of writing a formal essay, you could experiment with a narrative storytelling approach to engage the reader differently.
                """
        elif self.feedback_alternative_standard == 3:
            return """
                Present the standard solution clearly, but briefly mention one alternative approach.
                Example 1: QuickSort is efficient for large datasets, but for nearly sorted data, InsertionSort could be faster.
                Example 2: While a chronological structure works well for essays, you might briefly consider using a thematic structure.
                """
        else:  # 4 or 5
            return """
                Focus strictly on the most conventional, best-practice solution.
                Avoid suggesting alternatives unless necessary.
                Example 1: Use QuickSort for efficient large dataset sorting as it is widely considered the best practical choice.
                Example 2: Structure your essay with a clear introduction, body paragraphs supporting a single thesis, and a conclusion as per academic writing standards.
                """

    def directive_followup_summary(self) -> str:
        if self.feedback_followup_summary <= 2:
            return """
                End the feedback with an open-ended question that encourages further reflection or learning.
                Example 1: What challenges might arise if you deployed this architecture across multiple regions?
                Example 2: How would your marketing plan change if your target audience shifted to a younger demographic?
                """
        elif self.feedback_followup_summary == 3:
            return """
                Optionally conclude with either a follow-up question or a short summary, based on what feels most natural for the feedback content.
                """
        else:  # 4 or 5
            return """
                End the feedback with a concise summary highlighting the key takeaway.
                Example 1: In summary, optimizing query indexes significantly improves database read performance.
                Example 2: Overall, structuring your presentation around three key messages helps maintain audience engagement.
                """

    def directive_brief_detailed(self) -> str:
        if self.feedback_brief_detailed <= 2:
            return """
                Keep the feedback short and direct — ideally 1 to 2 sentences.
                Example 1: Add an index on the user_id column to improve performance.
                Example 2: Clarify your thesis statement in the introduction to strengthen your argument.
                """
        elif self.feedback_brief_detailed == 3:
            return """
                Provide moderately detailed feedback, giving clear explanations without unnecessary length.
                Example 1: Consider indexing user_id to speed up lookups; it helps databases quickly find matching records.
                Example 2: Starting your essay with a strong thesis helps guide the reader; this can also make your argumentation clearer.
                """
        else:  # 4 or 5
            return """
                Give detailed feedback with multiple sentences, examples, and background reasoning where relevant.
                Example 1: Adding an index on user_id improves query speed by allowing the database to locate relevant rows efficiently without scanning the entire table, which is crucial for scaling.
                Example 2: Introducing your main argument clearly in the essay’s opening not only frames the reader’s expectations but also strengthens your persuasiveness, a technique often recommended in academic writing.
                """

    def to_feedback_style_description(self) -> str:
        return (
            f"Please generate feedback according to the following instructions:\n"
            f"1. {self.directive_practical_theoretical()}\n"
            f"2. {self.directive_alternative_standard()}\n"
            f"3. {self.directive_followup_summary()}\n"
            f"4. {self.directive_brief_detailed()}\n"
        )

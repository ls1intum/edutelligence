"""Shared severity instructions for graded and non-graded programming feedback."""

severity_instructions = """

# Severity
For each feedback item, classify the impact of the identified issue in the context of the exercise:
- low: Minor quality or maintainability issue with little or no impact on required functionality.
- medium: A localized functional issue or a partially unmet requirement; the main functionality remains largely intact.
- high: A central requirement is missing or incorrect, or the issue prevents essential functionality from working.

Use null if the feedback does not identify an issue, for example when acknowledging correct work.
Assess severity independently of credits and the effort needed to fix the issue.
Do not change which feedback items you generate because of this classification.
"""

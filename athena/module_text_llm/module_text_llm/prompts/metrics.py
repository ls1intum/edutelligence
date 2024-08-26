from pydantic import BaseModel, Field


class Metric(BaseModel):
    title: str
    summary: str
    description: str


class MetricEvaluation(BaseModel):
    title: str = Field(..., description="The title of the metric.")
    score: int = Field(..., ge=1, le=5, description="The score of the metric.")


class MetricEvaluations(BaseModel):
    evaluations: list[MetricEvaluation] = Field(..., description="The evaluations of the metrics.")


correctness = Metric(
    title = 'Correctness',
    summary = 'Is the feedback free of factual errors?',
    description = """
    **Good**: The feedback accurately reflects the submission, solution, and criteria, with no errors.
    **Mid**: The feedback is mostly accurate but includes minor errors that don’t impact the overall evaluation.
    **Bad**: The feedback contains major errors that misrepresent the submission or solution, likely causing confusion.
    """
)

actionability = Metric(
    title = 'Actionability',
    summary = 'Can students realistically act on this feedback?',
    description = """
    **Good**: The feedback provides specific steps for improvement or reinforces correct approaches.
    **Mid**: The feedback notes correctness or errors but lacks detailed improvement guidance.
    **Bad**: The feedback identifies errors without solutions or offers no additional insights for correct work.
    """
)

tone = Metric(
    title = 'Tone',
    summary = 'Is the feedback respectful and constructive?',
    description = """
    **Good**: The feedback is respectful and constructive, recognizing both strengths and areas for improvement.
    **Mid**: The feedback is professional but mainly corrective, with little positive reinforcement.
    **Bad**: The feedback is overly critical or dismissive, using unprofessional or disrespectful language.
    """
)

completeness = Metric(
    title = 'Completeness',
    summary = 'Does the feedback cover all relevant aspects without unnecessary information?',
    description = """
    **Good**: The feedback addresses all key aspects and avoids irrelevant details.
    **Mid**: The feedback covers most important points but may miss minor details or include some irrelevant information.
    **Bad**: The feedback misses important aspects or includes too much irrelevant content.
    """
)

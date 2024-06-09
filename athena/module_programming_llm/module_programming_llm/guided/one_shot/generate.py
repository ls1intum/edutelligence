import os
from typing import List, Optional, Sequence
from pydantic import BaseModel, Field

from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

from athena.programming import Exercise, Submission, Feedback

from .config import GuidedOneShotConfig

from module_programming_llm.helpers.llm_utils import (
    num_tokens_from_string,
    predict_and_parse,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
    add_line_numbers,
    get_programming_language_file_extension,
)


class FeedbackModel(BaseModel):
    file_path: Optional[str] = Field(description="File path of the feedback, or empty if unreferenced")
    line_start: Optional[int] = Field(
        description="Referenced line number start, or empty if unreferenced"
    )
    line_end: Optional[int] = Field(
        description="Referenced line number end, or empty if unreferenced"
    )
    description: str = Field(description="Guided feedback description")

    class Config:
        title = "GuidedFeedback"


class GuidedFeedbackCompendiumModel(BaseModel):
    """Compendium of guided feedbacks for a submission."""

    guided_feedbacks: Sequence[FeedbackModel] = Field(description="Guided feedbacks")

    class Config:
        title = "GuidedFeedbackCompendium"


# pylint: disable=too-many-locals
async def generate_guided_one_shot_suggestions(
    exercise: Exercise,
    submission: Submission,
    config: GuidedOneShotConfig,
    debug: bool,
) -> List[Feedback]:
    model = config.model.get_model()  # type: ignore[attr-defined]

    system_message_prompt = SystemMessagePromptTemplate.from_template(config.prompt.system_message)
    problem_message_prompt = HumanMessagePromptTemplate.from_template(config.prompt.problem_message)
    file_message_prompt = HumanMessagePromptTemplate.from_template(config.prompt.file_message)
    
    prompt_inputs: List[dict] = []

    # Feature extraction
    template_repo = exercise.get_template_repository()
    solution_repo = exercise.get_solution_repository()
    submission_repo = submission.get_repository()

    changed_files_from_template_to_submission = get_diff(
        src_repo=template_repo, dst_repo=submission_repo, file_path=None, name_only=True
    ).split("\n")
    changed_files_from_template_to_submission = [
        os.path.join(str(submission_repo.working_tree_dir or ""), file_path)
        for file_path in changed_files_from_template_to_submission
    ]

    # Changed text files
    changed_files = load_files_from_repo(
        submission_repo,
        file_filter=lambda file_path: file_path
        in changed_files_from_template_to_submission,
    )

    problem_statement = exercise.problem_statement or ""
    problem_statement = (
        problem_statement
        if problem_statement.strip()
        else "No problem statement found."
    )

    programming_language_extension = get_programming_language_file_extension(
        programming_language=exercise.programming_language
    )

    # Gather prompt inputs for each changed file (independently)
    for file_path, file_content in changed_files.items():
        if programming_language_extension and not file_path.endswith(programming_language_extension):
            continue

        file_content = add_line_numbers(file_content)
        solution_to_submission_diff = get_diff(
            src_repo=solution_repo,
            dst_repo=submission_repo,
            src_prefix="solution",
            dst_prefix="submission",
            file_path=file_path,
        )
        template_to_submission_diff = get_diff(
            src_repo=template_repo,
            dst_repo=submission_repo,
            src_prefix="template",
            dst_prefix="submission",
            file_path=file_path,
        )
        template_to_solution_diff = get_diff(
            src_repo=template_repo,
            dst_repo=solution_repo,
            src_prefix="template",
            dst_prefix="solution",
            file_path=file_path,
        )

        prompt_inputs.append(
            {
                "file_path": file_path,
                "submission_file": file_content,
                "solution_to_submission_diff": solution_to_submission_diff,
                "template_to_submission_diff": template_to_submission_diff,
                "template_to_solution_diff": template_to_solution_diff,
            }
        )

    prompt_input = {
        "problem_statement": problem_statement,
        "prompt_inputs": prompt_inputs,
    }

    chat_prompt = ChatPromptTemplate.from_messages(
        [system_message_prompt, problem_message_prompt]
        + [file_message_prompt.format(**prompt_input) for prompt_input in prompt_inputs]
    )

    results: Optional[GuidedFeedbackCompendiumModel] = await predict_and_parse(
        model=model,
        chat_prompt=chat_prompt,
        prompt_input=prompt_input,
        pydantic_object=GuidedFeedbackCompendiumModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
            "one-shot-non-graded-suggestions",
        ],
    )

    feedbacks: List[Feedback] = []
    if results is not None:
        for feedback in results.guided_feedbacks:
            feedbacks.append(
                Feedback(
                    id=None,
                    exercise_id=exercise.id,
                    submission_id=submission.id,
                    title="Guided Feedback",
                    description=feedback.description,
                    file_path=feedback.file_path,
                    line_start=feedback.line_start,
                    line_end=feedback.line_end,
                    is_graded=False,
                    credits=0,
                    structured_grading_instruction_id=None,
                    meta={},
                )
            )

    return feedbacks

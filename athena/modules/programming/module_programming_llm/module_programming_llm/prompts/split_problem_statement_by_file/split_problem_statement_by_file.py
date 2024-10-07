from collections import defaultdict
from typing import Optional

from pydantic import Field

from athena import emit_meta
from .prompt import system_message, human_message

from .split_problem_statement_by_file_input import SplitProblemStatementByFileInput
from .split_problem_statement_by_file_output import FileProblemStatement, SplitProblemStatementByFileOutput
from ..pipeline_step import PipelineStep
from ...helpers.llm_utils import num_tokens_from_string, get_chat_prompt_with_formatting_instructions, \
    num_tokens_from_prompt, predict_and_parse
from ...helpers.models import ModelConfigType
from ...helpers.utils import get_diff


class SplitProblemStatementByFile(PipelineStep[SplitProblemStatementByFileInput, SplitProblemStatementByFileOutput]):
    """Splits problem statement of a programming exercise to match with solution files"""

    system_message: str = Field(system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
    tokens_before_split: int = Field(default=250,
                                     description="Split the grading instructions into file-based ones after this number of tokens.")

    # pylint: disable=too-many-locals
    async def process(self, input_data: SplitProblemStatementByFileInput, debug: bool, model: ModelConfigType) -> \
    Optional[
        SplitProblemStatementByFileOutput]:
        """Split the general problem statement by file

        Args:
            input_data (SplitGradingInstructionsByFileInput): Input data containing template and submission repositories, programming exercise.

        Returns:
                Optional[SplitGradingInstructionsByFileOutput]: Split problem statement by file
        """

        # Return None if the problem statement is too short
        if num_tokens_from_string(input_data.problem_statement or "") <= self.tokens_before_split:
            return None

        template_repo = input_data.template_repo
        submission_repo = input_data.submission_repo

        changed_files_from_template_to_submission = get_diff(
            src_repo=template_repo,
            dst_repo=submission_repo,
            file_path=None,
            name_only=True
        ).split("\n")

        prompt = get_chat_prompt_with_formatting_instructions(
            model=model.get_model(),  # type: ignore[attr-defined]
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=SplitProblemStatementByFileOutput
        )

        prompt_input = {
            "problem_statement": input_data.problem_statement or "No problem statement.",
            "changed_files_from_template_to_submission": ", ".join(changed_files_from_template_to_submission)
        }

        if "changed_files_from_template_to_solution" in prompt.input_variables:
            solution_repo = input_data.solution_repo
            changed_files_from_template_to_solution = get_diff(
                src_repo=template_repo,
                dst_repo=solution_repo,
                file_path=None,
                name_only=True,
            ).split("\n")
            prompt_input["changed_files_from_template_to_solution"] = ", ".join(
                changed_files_from_template_to_solution
            )

        # Return None if the prompt is too long
        if num_tokens_from_prompt(prompt, prompt_input) > self.max_input_tokens:
            return None

        split_problem_statement = await predict_and_parse(
            model=model.get_model(),  # type: ignore[attr-defined]
            chat_prompt=prompt,
            prompt_input=prompt_input,
            pydantic_object=SplitProblemStatementByFileOutput,
            tags=[
                f"exercise-{input_data.exercise_id}",
                f"submission-{input_data.submission_id}",
                "split-problem-statement-by-file"
            ]
        )

        if debug:
            emit_meta("file_problem_statements", {
                "prompt": prompt.format(**prompt_input),
                "result": split_problem_statement.dict() if split_problem_statement is not None else None
            })

        if split_problem_statement is None or not split_problem_statement.items:
            return None

        # Join duplicate file names (some responses contain multiple problem statements for the same file)
        file_problem_statements_by_file_name = defaultdict(list)
        for file_problem_statement in split_problem_statement.items:
            file_problem_statements_by_file_name[file_problem_statement.file_path].append(file_problem_statement)

        split_problem_statement.items = [
            FileProblemStatement(
                file_path=file_name,
                problem_statement="\n".join(
                    file_problem_statement.problem_statement
                    for file_problem_statement in file_problem_statements
                )
            )
            for file_name, file_problem_statements in file_problem_statements_by_file_name.items()
        ]

        return split_problem_statement

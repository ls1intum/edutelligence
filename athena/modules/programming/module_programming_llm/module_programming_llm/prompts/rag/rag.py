import json
from typing import Optional

from athena import emit_meta
from module_programming_llm.prompts.pipeline_step import PipelineStep
from .rag_input import RAGInput
from .rag_output import RAGOutput
from .prompt import system_message as prompt_system_message, human_message as prompt_human_message
from pydantic import Field
from module_programming_llm.helpers.llm_utils import (
    get_chat_prompt_with_formatting_instructions,
    predict_and_parse,
    num_tokens_from_prompt,
)
from module_programming_llm.helpers.utils import (
    get_diff,
    load_files_from_repo,
)
from ...helpers.models import ModelConfigType


class RAG(PipelineStep[RAGInput, Optional[RAGOutput]]):
    """Generates RAG queries."""

    system_message: str = Field(prompt_system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(prompt_human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")

    async def process(self, input_data: RAGInput, debug: bool, model: ModelConfigType) -> Optional[
        RAGOutput]:  # type: ignore
        model = model.get_model()  # type: ignore[attr-defined]

        changed_files_from_template_to_solution = get_diff(
            src_repo=input_data.template_repo,
            dst_repo=input_data.solution_repo,
            file_path=None,
            name_only=True
        ).split("\n")

        changed_files = load_files_from_repo(
            input_data.solution_repo,
            file_filter=lambda file_path: file_path in changed_files_from_template_to_solution,
        )

        prompt = get_chat_prompt_with_formatting_instructions(
            model=model,
            system_message=self.system_message,
            human_message=self.human_message,
            pydantic_object=RAGOutput
        )

        prompt_input = {
            "problem_statement": input_data.problem_statement or "No problem statement.",
            "changed_files_from_template_to_solution": ", ".join(changed_files_from_template_to_solution),
            "template_to_solution_diff": json.dumps(changed_files)
        }

        # Return None if the prompt is too long
        if num_tokens_from_prompt(prompt, prompt_input) > self.max_input_tokens:
            return None

        generate_rag_queries = await predict_and_parse(
            model=model,
            chat_prompt=prompt,
            prompt_input=prompt_input,
            pydantic_object=RAGOutput,
            tags=[
                f"exercise-{input_data.exercise_id}",
                "generate_rag_requests"
            ]
        )

        if debug:
            emit_meta("generate_rag_requests", {
                "prompt": prompt.format(**prompt_input),
                "result": generate_rag_queries.dict() if generate_rag_queries is not None else None
            })

        return generate_rag_queries

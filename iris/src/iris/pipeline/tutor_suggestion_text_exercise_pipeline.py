import json
import logging
import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.llm import CompletionArguments, CapabilityRequestHandler, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.tutor_suggestion.text_exercise_prompt import text_exercise_prompt
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)

class TutorSuggestionTextExercisePipeline(Pipeline):

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorSuggestionCallback

    def __init__(self, callback: TutorSuggestionCallback):
        super().__init__(implementation_id="tutor_suggestion_text_exercise_pipeline")
        completion_args = CompletionArguments()
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(self_hosted=True)
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_arguments=completion_args,
        )

        self.callback = callback
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Tutor Suggestion Text Exercise Pipeline")
    def __call__(self, dto: TextExerciseDTO, chat_summary: str):
        result = "Error generating suggestions for text exercise"
        self.callback.in_progress("Generating suggestions for text exercise")
        text_exercise_result = self._run_text_exercise_pipeline(dto=dto, summary=chat_summary)
        try:
            result = text_exercise_result
        except Exception as e:
            logger.error(f"Failed to generate suggestions for text exercise: {e}")

        self.callback.done(
            "Generating suggestions for text exercise",
            final_result=result,
            tokens=self.tokens,
        )

    def _run_text_exercise_pipeline(self, dto, summary: str):
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    text_exercise_prompt(),
                )
            ]
        )
        try:
            response = (self.prompt | self.pipeline).invoke({
                "thread_summary": summary,
                "problem_statement": dto.problem_statement,
                "example_solution": dto.example_solution,
            })
            html_response = self._extract_html_from_text(response)
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_TUTOR_SUGGESTION_PIPELINE
            )
            return html_response
        except Exception as e:
            raise e

    @staticmethod
    def _extract_html_from_text(text: str):
        html_pattern = re.compile(r"answer:\s*(?P<html>&lt;ul&gt;.*?&lt;/ul&gt;|<ul>.*?</ul>)", re.DOTALL)
        match = html_pattern.search(text)

        if match:
            return match.group("html").strip()
        else:
            logger.error("No HTML found after 'answer:' in text.")
            return None

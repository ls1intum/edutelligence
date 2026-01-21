from typing import List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.prompts.lecture_unit_summary_prompt import (
    lecture_unit_summary_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe


class LectureUnitSummaryPipeline(SubPipeline):
    """LectureUnitSummaryPipeline summarizes lecture unit segments into a cohesive summary
    by constructing and invoking a language model pipeline with a custom prompt.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate

    def __init__(
        self,
        client: WeaviateClient,
        lecture_unit_dto: LectureUnitDTO,
        lecture_unit_segment_summaries: List[str],
        local: bool = False,
    ) -> None:
        super().__init__()
        self.client = client
        self.lecture_unit_dto = lecture_unit_dto
        self.lecture_unit_segment_summaries = lecture_unit_segment_summaries

        request_handler = ModelVersionRequestHandler(
            version="llama3.3:latest" if local else "gpt-4.1-mini"
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)

        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @observe(name="Lecture Unit Summary Pipeline")
    def __call__(self, *args, **kwargs):
        lecture_unit_segment_text = ""
        for summary in self.lecture_unit_segment_summaries:
            lecture_unit_segment_text += f"{summary}\n"

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    lecture_unit_summary_prompt(
                        self.lecture_unit_dto, lecture_unit_segment_text
                    ),
                ),
            ]
        )
        formatted_prompt = self.prompt.format_messages()
        self.prompt = ChatPromptTemplate.from_messages(formatted_prompt)
        try:
            response = (self.prompt | self.pipeline).invoke({})
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_LECTURE_SUMMARY_PIPELINE
            )
            return response, self.tokens
        except Exception as e:
            raise e

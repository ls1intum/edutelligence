import datetime
import os
from enum import Enum

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
)
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
from iris.vector_database.faq_schema import FaqSchema

logger = get_logger(__name__)


class InformationType(str, Enum):
    PARAGRAPHS = "PARAGRAPHS"
    FAQS = "FAQS"


class CitationPipeline(SubPipeline):
    """A generic reranker pipeline that can be used to rerank a list of documents based on a question"""

    llms: dict
    pipelines: dict
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="citation_pipeline")
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(dirname, "..", "prompts", "citation_prompt.txt")
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.lecture_prompt_str = file.read()
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "faq_citation_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.faq_prompt_str = file.read()
        self.tokens = []

        # Create LLM variants
        self.llms = {}
        self.pipelines = {}

        # Default variant
        default_request_handler = ModelVersionRequestHandler(
            version="llama3.3:latest" if local else "gpt-4.1-nano"
        )
        default_llm = IrisLangchainChatModel(
            request_handler=default_request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        self.llms["default"] = default_llm
        self.pipelines["default"] = default_llm | StrOutputParser()

        # Advanced variant
        advanced_request_handler = ModelVersionRequestHandler(
            version="llama3.3:latest" if local else "gpt-4.1-mini"
        )
        advanced_llm = IrisLangchainChatModel(
            request_handler=advanced_request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        self.llms["advanced"] = advanced_llm
        self.pipelines["advanced"] = advanced_llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llms={list(self.llms.keys())})"

    def __str__(self):
        return f"{self.__class__.__name__}(llms={list(self.llms.keys())})"

    def create_formatted_lecture_string(
        self, lecture_retrieval_dto: LectureRetrievalDTO
    ):
        """
        Create a formatted string from the data
        """

        formatted_string_lecture_page_chunks = ""
        for paragraph in lecture_retrieval_dto.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            # Temporary fix for wrong links, e.g. https://artemis.tum.deattachments/...
            if ".deattachment" in paragraph.lecture_unit_link:
                paragraph.lecture_unit_link = paragraph.lecture_unit_link.replace(
                    ".deattachment", ".de/api/core/files/attachment"
                )
            lct = (
                f"Lecture: {paragraph.lecture_name},"
                f" Unit: {paragraph.lecture_unit_name},"
                f" Page: {paragraph.page_number},"
                f" Link: {paragraph.lecture_unit_link or "No link available"},"
                f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )
            formatted_string_lecture_page_chunks += lct

        formatted_string_lecture_transcriptions = ""

        for paragraph in lecture_retrieval_dto.lecture_transcriptions:
            start_time_sec = paragraph.segment_start_time
            end_time_sec = paragraph.segment_end_time
            start_time_str = str(datetime.timedelta(seconds=int(start_time_sec)))
            end_time_str = str(datetime.timedelta(seconds=int(end_time_sec)))
            lct = (
                f"Lecture Transcription: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}, Link: {paragraph.video_link or "No link available"}, "
                f"Start Time: {start_time_str}, End Time: {end_time_str},\n"
                f"Content:\n"
                f"---{paragraph.segment_text}---\n\n"
            )
            formatted_string_lecture_transcriptions += lct
        return formatted_string_lecture_page_chunks.replace("{", "{{").replace(
            "}", "}}"
        ), formatted_string_lecture_transcriptions.replace("{", "{{").replace("}", "}}")

    def create_formatted_faq_string(self, faqs, base_url):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for faq in faqs:
            faq = (
                f"FAQ ID {faq.get(FaqSchema.FAQ_ID.value)},"
                f" CourseId {faq.get(FaqSchema.COURSE_ID.value)} ,"
                f" FAQ Question title {faq.get(FaqSchema.QUESTION_TITLE.value)} and"
                f" FAQ Question Answer {faq.get(FaqSchema.QUESTION_ANSWER.value)} and"
                f" FAQ link {base_url}/courses/{faq.get(FaqSchema.COURSE_ID.value)}/faq/?faqId="
                f"{faq.get(FaqSchema.FAQ_ID.value)}"
            )
            formatted_string += faq

        return formatted_string.replace("{", "{{").replace("}", "}}")

    @observe(name="Citation Pipeline")
    def __call__(
        self,
        information,  #: #Union[List[dict], List[str]],
        answer: str,
        information_type: InformationType = InformationType.PARAGRAPHS,
        variant: str = "default",
        user_language: str = "en",
        **kwargs,
    ) -> str:
        """
        Runs the pipeline
            :param information: List of info as list of dicts or strings to augment response
            :param query: The query
            :param information_type: The type of information provided. can be either lectures or faqs
            :param variant: The variant of the model to use ("default" or "advanced")
            :param user_language: The user's preferred language ("en" or "de")
            :return: Selected file content
        """
        paras = ""
        paragraphs_page_chunks = ""
        paragraphs_transcriptions = ""

        if variant not in self.llms:
            variant = "default"

        llm = self.llms[variant]
        pipeline = self.pipelines[variant]

        if information_type == InformationType.FAQS:
            paras = self.create_formatted_faq_string(
                information, kwargs.get("base_url")
            )
            self.prompt_str = self.faq_prompt_str
        if information_type == InformationType.PARAGRAPHS:
            paragraphs_page_chunks, paragraphs_transcriptions = (
                self.create_formatted_lecture_string(information)
            )
            self.prompt_str = self.lecture_prompt_str

        # Add language instruction to prompt
        if user_language == "de":
            language_instruction = "Format all citations and references in German.\n\n"
        else:
            language_instruction = "Format all citations and references in English.\n\n"

        try:
            self.default_prompt = PromptTemplate(
                template=language_instruction + self.prompt_str,
                input_variables=["Answer", "Paragraphs"],
            )
            if information_type == InformationType.FAQS:
                response = (self.default_prompt | pipeline).invoke(
                    {"Answer": answer, "Paragraphs": paras}
                )
            else:
                response = (self.default_prompt | pipeline).invoke(
                    {
                        "Answer": answer,
                        "Paragraphs": paragraphs_page_chunks,
                        "TranscriptionParagraphs": paragraphs_transcriptions,
                    }
                )
            self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            if "!NONE!" in str(response):
                return answer
            return response
        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            raise e

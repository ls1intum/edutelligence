import os
import json
import re
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

    def __init__(self):
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
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "citation_keyword_summary_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.keyword_summary_prompt_str = file.read()
        self.tokens = []
        self.used_citation_numbers: list[int] = []
        self._last_citation_content_by_seq: dict[int, str] = {}

        # Create LLM variants
        self.llms = {}
        self.pipelines = {}

        # Default variant
        default_request_handler = ModelVersionRequestHandler(version="gpt-4.1-nano")
        default_llm = IrisLangchainChatModel(
            request_handler=default_request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        self.llms["default"] = default_llm
        self.pipelines["default"] = default_llm | StrOutputParser()

        # Advanced variant
        advanced_request_handler = ModelVersionRequestHandler(version="gpt-4.1-mini")
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
        def build_citation_id(
            lecture_unit_id,
            page_number=None,
            start_time_sec=None,
            end_time_sec=None,
            seq=None,
        ):
            def format_part(value):
                return "" if value is None else str(value)

            return (
                "[cite:L:"
                f"{format_part(lecture_unit_id)}:"
                f"{format_part(page_number)}:"
                f"{format_part(start_time_sec)}:"
                f"{format_part(end_time_sec)}"
                f"!{format_part(seq)}]"
            )

        seq = 0
        self._last_citation_content_by_seq = {}
        lecture_page_chunks = []
        for paragraph in lecture_retrieval_dto.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            seq += 1
            self._last_citation_content_by_seq[seq] = paragraph.page_text_content
            lecture_page_chunks.append(
                {
                    "id": build_citation_id(
                        paragraph.lecture_unit_id,
                        paragraph.page_number,
                        None,
                        None,
                        seq,
                    ),
                    "content": paragraph.page_text_content,
                }
            )

        lecture_transcriptions = []
        for paragraph in lecture_retrieval_dto.lecture_transcriptions:
            start_time_sec = (
                int(paragraph.segment_start_time)
                if paragraph.segment_start_time is not None
                else None
            )
            end_time_sec = (
                int(paragraph.segment_end_time)
                if paragraph.segment_end_time is not None
                else None
            )
            seq += 1
            self._last_citation_content_by_seq[seq] = paragraph.segment_text
            lecture_transcriptions.append(
                {
                    "id": build_citation_id(
                        paragraph.lecture_unit_id,
                        paragraph.page_number,
                        start_time_sec,
                        end_time_sec,
                        seq,
                    ),
                    "content": paragraph.segment_text,
                }
            )

        formatted_string = json.dumps(
            lecture_page_chunks + lecture_transcriptions,
            ensure_ascii=True,
        )
        return formatted_string.replace("{", "{{").replace("}", "}}")

    def create_formatted_faq_string(self, faqs):
        """
        Create a formatted string from the data
        """
        formatted_faqs = []
        seq = 0
        self._last_citation_content_by_seq = {}
        for faq in faqs:
            seq += 1
            faq_id = faq.get(FaqSchema.FAQ_ID.value)
            question = faq.get(FaqSchema.QUESTION_TITLE.value)
            answer = faq.get(FaqSchema.QUESTION_ANSWER.value)
            content = f"{question} {answer}".strip()
            self._last_citation_content_by_seq[seq] = content
            formatted_faqs.append(
                {
                    "id": f"[cite:F:{faq_id}:::!{seq}]",
                    "content": content,
                }
            )

        formatted_string = json.dumps(formatted_faqs, ensure_ascii=True)
        return formatted_string.replace("{", "{{").replace("}", "}}")

    def extract_used_citation_numbers(self, answer: str) -> list[int]:
        """
        Extracts the numeric suffix after '!' from citation blocks in the answer.
        Example block: [cite:L/F:entityid:page:start:end!number]
        """
        if not answer:
            return []
        numbers = []
        for match in re.finditer(r"\[cite:[LF]:[^]]*?!(\d+)\]", answer):
            numbers.append(int(match.group(1)))
        return numbers

    def _sanitize_citation_field(self, value: str) -> str:
        if not value:
            return ""
        cleaned = value.replace(":", " -").replace("]", ")").replace("[", "(")
        return " ".join(cleaned.split())

    def _parse_keyword_summary_response(self, raw: str) -> tuple[str, str]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "", ""
        keyword = self._sanitize_citation_field(str(data.get("keyword", "")).strip())
        summary = self._sanitize_citation_field(str(data.get("summary", "")).strip())
        return keyword, summary

    def _build_keyword_summary_map(
        self,
        pipeline,
        language_instruction: str,
        used_numbers: list[int],
        user_language: str,
    ) -> dict[int, tuple[str, str]]:
        summary_prompt = PromptTemplate(
            template=language_instruction + self.keyword_summary_prompt_str,
            input_variables=["Paragraph", "UsedKeywords"],
        )
        summaries: dict[int, tuple[str, str]] = {}
        seen: set[int] = set()
        used_keywords: set[str] = set()
        for num in used_numbers:
            if num in seen:
                continue
            seen.add(num)
            paragraph = self._last_citation_content_by_seq.get(num, "")
            if not paragraph.strip():
                summaries[num] = ("", "")
                continue
            used_keywords_str = ", ".join(sorted(used_keywords))
            raw = str(
                (summary_prompt | pipeline).invoke(
                    {"Paragraph": paragraph, "UsedKeywords": used_keywords_str}
                )
            ).strip()
            keyword, summary = self._parse_keyword_summary_response(raw)
            if keyword:
                used_keywords.add(keyword)
            summaries[num] = (keyword, summary)
        return summaries

    def _replace_cite_blocks_with_keyword_summary(
        self, answer: str, summaries: dict[int, tuple[str, str]]
    ) -> str:
        def _replace(m: re.Match) -> str:
            cite_type = m.group(1)
            entity_id = m.group(2)
            page = m.group(3)
            start = m.group(4)
            end = m.group(5)
            num = int(m.group(7))
            keyword, summary = summaries.get(num, ("", ""))
            return (
                f"[cite:{cite_type}:{entity_id}:{page}:{start}:{end}:"
                f"{keyword}:{summary}]"
            )

        return re.sub(
            r"\[cite:([LF]):([^:\]]*):([^:\]]*):([^:\]]*):([^:\]]*)(?::([^!\]]*))?!(\d+)\]",
            _replace,
            answer,
        )

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
        paragraphs = ""

        if variant not in self.llms:
            variant = "default"

        llm = self.llms[variant]
        pipeline = self.pipelines[variant]

        if information_type == InformationType.FAQS:
            paragraphs = self.create_formatted_faq_string(information)
            self.prompt_str = self.faq_prompt_str
        if information_type == InformationType.PARAGRAPHS:
            paragraphs = self.create_formatted_lecture_string(information)
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
            response = (self.default_prompt | pipeline).invoke(
                {"Answer": answer, "Paragraphs": paragraphs}
            )
            self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            response_str = str(response)
            self.used_citation_numbers = self.extract_used_citation_numbers(response_str)
            summaries = self._build_keyword_summary_map(
                pipeline=pipeline,
                language_instruction=language_instruction,
                used_numbers=self.used_citation_numbers,
                user_language=user_language,
            )
            response_str = self._replace_cite_blocks_with_keyword_summary(
                response_str, summaries
            )
            return response_str
        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            raise e

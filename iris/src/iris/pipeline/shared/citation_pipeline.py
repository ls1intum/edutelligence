import os
import re
from enum import Enum

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

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

    def __init__(self):
        super().__init__(implementation_id="citation_pipeline")
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(dirname, "..", "prompts", "citation_prompt.txt")
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.lecture_prompt_str = file.read()
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "citation_keyword_summary_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.citation_keyword_summary_prompt_str = file.read()
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

        formatted_string_lecture_page_chunks = ""
        for paragraph in lecture_retrieval_dto.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            lct = (
                f"Lecture Unit ID: {paragraph.lecture_unit_id},"
                f" Page: {paragraph.page_number},"
                f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )
            formatted_string_lecture_page_chunks += lct

        formatted_string_lecture_transcriptions = ""

        for paragraph in lecture_retrieval_dto.lecture_transcriptions:
            start_time_sec = paragraph.segment_start_time
            end_time_sec = paragraph.segment_end_time
            lct = (
                f"Lecture Unit ID: {paragraph.lecture_unit_id}, "
                f"Page: {paragraph.page_number}, "
                f"Start Time Seconds: {int(start_time_sec)}, "
                f"End Time Seconds: {int(end_time_sec)},\n"
                f"Content:\n"
                f"---{paragraph.segment_text}---\n\n"
            )
            formatted_string_lecture_transcriptions += lct
        return formatted_string_lecture_page_chunks.replace("{", "{{").replace(
            "}", "}}"
        ), formatted_string_lecture_transcriptions.replace("{", "{{").replace("}", "}}")

    def create_formatted_faq_string(self, faqs):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for faq in faqs:
            faq = (
                f"FAQ ID: {faq.get(FaqSchema.FAQ_ID.value)}, "
                f"FAQ Question Title: {faq.get(FaqSchema.QUESTION_TITLE.value)}, "
                f"FAQ Answer: {faq.get(FaqSchema.QUESTION_ANSWER.value)}"
            )
            formatted_string += faq

        return formatted_string.replace("{", "{{").replace("}", "}}")

    _TRANSCRIPTION_CITATION_RE = re.compile(
        r"^\[(\d+)\]\s*Lecture Unit ID:\s*(\d+)(?:,\s*Page:\s*(\d+))?,\s*Start:\s*(\d+),\s*End:\s*(\d+)\s*$"
    )
    _SLIDE_CITATION_RE = re.compile(
        r"^\[(\d+)\]\s*Lecture Unit ID:\s*(\d+),\s*Page:\s*(\d+)\s*$"
    )
    _FAQ_CITATION_RE = re.compile(r"^\[(\d+)\]\s*FAQ ID:\s*(\d+)\s*$")
    _KEYWORD_SUMMARY_RE = re.compile(
        r"^\[(\d+)\]\s*Keyword:\s*(.*?);\s*Summary:\s*(.+)\s*$"
    )

    def _extract_citation_entries(self, response_text: str):
        entries = []
        for raw_line in response_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("["):
                continue
            match = self._TRANSCRIPTION_CITATION_RE.match(line)
            if match:
                entries.append(
                    {
                        "index": int(match.group(1)),
                        "type": "transcription",
                        "lecture_unit_id": int(match.group(2)),
                        "page_number": (
                            int(match.group(3)) if match.group(3) is not None else None
                        ),
                        "start": int(match.group(4)),
                        "end": int(match.group(5)),
                    }
                )
                continue
            match = self._SLIDE_CITATION_RE.match(line)
            if match:
                entries.append(
                    {
                        "index": int(match.group(1)),
                        "type": "slide",
                        "lecture_unit_id": int(match.group(2)),
                        "page_number": int(match.group(3)),
                    }
                )
        return entries

    def _extract_faq_citation_entries(self, response_text: str):
        entries = []
        for raw_line in response_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("["):
                continue
            match = self._FAQ_CITATION_RE.match(line)
            if match:
                entries.append(
                    {
                        "index": int(match.group(1)),
                        "faq_id": int(match.group(2)),
                    }
                )
        return entries

    def _format_citation_content(
        self, entries, lecture_retrieval_dto: LectureRetrievalDTO
    ) -> str:
        slide_content_map = {}
        for paragraph in lecture_retrieval_dto.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            slide_content_map[(paragraph.lecture_unit_id, paragraph.page_number)] = (
                paragraph.page_text_content
            )

        transcription_content_map = {}
        for paragraph in lecture_retrieval_dto.lecture_transcriptions:
            if not paragraph.segment_text:
                continue
            transcription_content_map[
                (
                    paragraph.lecture_unit_id,
                    paragraph.page_number,
                    int(paragraph.segment_start_time),
                    int(paragraph.segment_end_time),
                )
            ] = paragraph.segment_text

        formatted = ""
        for entry in entries:
            if entry["type"] == "transcription":
                key_with_page = (
                    entry["lecture_unit_id"],
                    entry["page_number"],
                    entry["start"],
                    entry["end"],
                )
                key_without_page = (
                    entry["lecture_unit_id"],
                    None,
                    entry["start"],
                    entry["end"],
                )
                content = transcription_content_map.get(
                    key_with_page,
                    transcription_content_map.get(key_without_page, ""),
                )
                page_number = entry["page_number"]
                page_part = f", Page: {page_number}" if page_number is not None else ""
                index = entry["index"]
                lecture_unit_id = entry["lecture_unit_id"]
                start = entry["start"]
                end = entry["end"]
                formatted += (
                    f"[{index}] Lecture Unit ID: {lecture_unit_id}"
                    f"{page_part}, Start: {start}, End: {end}\n"
                    f"Content:\n---{content}---\n\n"
                )
            else:
                key = (entry["lecture_unit_id"], entry["page_number"])
                content = slide_content_map.get(key, "")
                index = entry["index"]
                lecture_unit_id = entry["lecture_unit_id"]
                page_number = entry["page_number"]
                formatted += (
                    f"[{index}] Lecture Unit ID: {lecture_unit_id}, "
                    f"Page: {page_number}\n"
                    f"Content:\n---{content}---\n\n"
                )

        return formatted.replace("{", "{{").replace("}", "}}")

    def _format_faq_citation_content(self, entries, faqs) -> str:
        faq_content_map = {}
        for faq in faqs:
            faq_id = faq.get(FaqSchema.FAQ_ID.value)
            if faq_id is None:
                continue
            title = faq.get(FaqSchema.QUESTION_TITLE.value, "")
            answer = faq.get(FaqSchema.QUESTION_ANSWER.value, "")
            faq_content_map[int(faq_id)] = (
                f"FAQ Question Title: {title}\nFAQ Answer: {answer}"
            )

        formatted = ""
        for entry in entries:
            content = faq_content_map.get(entry["faq_id"], "")
            index = entry["index"]
            faq_id = entry["faq_id"]
            formatted += (
                f"[{index}] FAQ ID: {faq_id}\n" f"Content:\n---{content}---\n\n"
            )

        return formatted.replace("{", "{{").replace("}", "}}")

    def _split_answer_citation_blocks(self, response_text: str):
        lines = response_text.splitlines()

        # Collect keyword/summary lines from the bottom.
        keyword_lines = []
        idx = len(lines) - 1
        while idx >= 0 and not lines[idx].strip():
            idx -= 1
        while idx >= 0 and self._KEYWORD_SUMMARY_RE.match(lines[idx].strip()):
            keyword_lines.append(lines[idx].strip())
            idx -= 1
        keyword_lines.reverse()

        # Skip trailing blanks and stray !NONE!/header lines between blocks.
        while idx >= 0 and (
            not lines[idx].strip()
            or lines[idx].strip() == "!NONE!"
            or lines[idx].strip().lower() in {"citations:", "**citations:**"}
        ):
            idx -= 1

        # Collect citation list lines.
        citation_lines = []
        while idx >= 0:
            line = lines[idx].strip()
            if line == "!NONE!" or line.lower() in {"citations:", "**citations:**"}:
                idx -= 1
                continue
            if (
                self._TRANSCRIPTION_CITATION_RE.match(line)
                or self._SLIDE_CITATION_RE.match(line)
                or self._FAQ_CITATION_RE.match(line)
            ):
                citation_lines.append(line)
                idx -= 1
                continue
            break
        citation_lines.reverse()

        # The rest is the answer body.
        answer_lines = lines[: idx + 1]
        answer_text = "\n".join(answer_lines).rstrip()

        return answer_text, citation_lines, keyword_lines

    def _build_citation_map(self, citation_lines, keyword_lines):
        keyword_map = {}
        for line in keyword_lines:
            match = self._KEYWORD_SUMMARY_RE.match(line.strip())
            if not match:
                continue
            idx = int(match.group(1))
            keyword_map[idx] = (match.group(2).strip(), match.group(3).strip())

        citation_map = {}
        for line in citation_lines:
            line = line.strip()
            match = self._TRANSCRIPTION_CITATION_RE.match(line)
            if match:
                idx = int(match.group(1))
                lecture_unit_id = int(match.group(2))
                page = match.group(3) if match.group(3) is not None else ""
                start = match.group(4)
                end = match.group(5)
                if start == end:
                    start = ""
                    end = ""
                keyword, summary = keyword_map.get(idx, ("", ""))
                citation_map[idx] = {
                    "type": "L",
                    "id": str(lecture_unit_id),
                    "page": page,
                    "start": start,
                    "end": end,
                    "keyword": keyword,
                    "summary": summary,
                }
                continue

            match = self._SLIDE_CITATION_RE.match(line)
            if match:
                idx = int(match.group(1))
                lecture_unit_id = int(match.group(2))
                page = match.group(3)
                keyword, summary = keyword_map.get(idx, ("", ""))
                citation_map[idx] = {
                    "type": "L",
                    "id": str(lecture_unit_id),
                    "page": page,
                    "start": "",
                    "end": "",
                    "keyword": keyword,
                    "summary": summary,
                }
                continue

            match = self._FAQ_CITATION_RE.match(line)
            if match:
                idx = int(match.group(1))
                faq_id = int(match.group(2))
                keyword, summary = keyword_map.get(idx, ("", ""))
                citation_map[idx] = {
                    "type": "F",
                    "id": str(faq_id),
                    "page": "",
                    "start": "",
                    "end": "",
                    "keyword": keyword,
                    "summary": summary,
                }

        return citation_map

    def _inline_citations_and_strip_blocks(self, response_text: str) -> str:
        if response_text.strip() == "!NONE!":
            return response_text.strip()

        answer_text, citation_lines, keyword_lines = self._split_answer_citation_blocks(
            response_text
        )
        if not citation_lines:
            return response_text.strip()

        citation_map = self._build_citation_map(citation_lines, keyword_lines)
        if not citation_map:
            return answer_text or response_text.strip()

        def _replace(match):
            idx = int(match.group(1))
            data = citation_map.get(idx)
            if not data:
                return match.group(0)
            citation_type = data["type"]
            citation_id = data["id"]
            page = data["page"]
            start = data["start"]
            end = data["end"]
            keyword = data["keyword"]
            summary = data["summary"]
            return (
                f"[cite:{citation_type}:{citation_id}:{page}:"
                f"{start}:{end}:{keyword}:{summary}]"
            )

        return re.sub(r"\[(\d+)\]", _replace, answer_text)

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
            :return: Answer text with inline citations added
        """
        paras = ""
        paragraphs_page_chunks = ""
        paragraphs_transcriptions = ""

        if variant not in self.llms:
            variant = "default"

        llm = self.llms[variant]
        pipeline = self.pipelines[variant]

        if information_type == InformationType.FAQS:
            paras = self.create_formatted_faq_string(information) or ""
            self.prompt_str = self.faq_prompt_str
        if information_type == InformationType.PARAGRAPHS:
            paragraphs_page_chunks, paragraphs_transcriptions = (
                self.create_formatted_lecture_string(information)
            )
            paragraphs_page_chunks = paragraphs_page_chunks or ""
            paragraphs_transcriptions = paragraphs_transcriptions or ""
            self.prompt_str = self.lecture_prompt_str

        # Add language instruction to prompt
        if user_language == "de":
            language_instruction = "Format all citations and references in German.\n\n"
        else:
            language_instruction = "Format all citations and references in English.\n\n"

        try:
            if information_type == InformationType.FAQS:
                self.default_prompt = PromptTemplate(
                    template=language_instruction + self.prompt_str,
                    input_variables=[
                        "Answer",
                        "Paragraphs",
                    ],
                )
                response = (self.default_prompt | pipeline).invoke(
                    {
                        "Answer": answer,
                        "Paragraphs": paras,
                    }
                )
            else:
                self.default_prompt = PromptTemplate(
                    template=language_instruction + self.prompt_str,
                    input_variables=[
                        "Answer",
                        "Paragraphs",
                        "TranscriptionParagraphs",
                    ],
                )
                response = (self.default_prompt | pipeline).invoke(
                    {
                        "Answer": answer,
                        "Paragraphs": paragraphs_page_chunks,
                        "TranscriptionParagraphs": paragraphs_transcriptions,
                    }
                )
            self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            response_text = str(response).strip()

            if information_type == InformationType.PARAGRAPHS and isinstance(
                information, LectureRetrievalDTO
            ):
                _, citation_lines, _ = self._split_answer_citation_blocks(response_text)
                if citation_lines:
                    citations_block = "\n".join(citation_lines).strip()
                    paragraphs_block = (
                        (paragraphs_page_chunks or "").strip()
                        + "\n\n"
                        + (paragraphs_transcriptions or "").strip()
                    ).strip()
                    if citations_block and paragraphs_block:
                        keyword_prompt = PromptTemplate(
                            template=language_instruction
                            + self.citation_keyword_summary_prompt_str,
                            input_variables=[
                                "Citations",
                                "Paragraphs",
                            ],
                        )
                        keyword_response = (keyword_prompt | pipeline).invoke(
                            {
                                "Citations": citations_block,
                                "Paragraphs": paragraphs_block,
                            }
                        )
                        self._append_tokens(
                            llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE
                        )
                        response_text = (
                            response_text.rstrip()
                            + "\n\n"
                            + str(keyword_response).strip()
                        )
            if information_type == InformationType.FAQS and isinstance(
                information, list
            ):
                _, citation_lines, _ = self._split_answer_citation_blocks(response_text)
                if citation_lines:
                    citations_block = "\n".join(citation_lines).strip()
                    paragraphs_block = (paras or "").strip()
                    if citations_block and paragraphs_block:
                        keyword_prompt = PromptTemplate(
                            template=language_instruction
                            + self.citation_keyword_summary_prompt_str,
                            input_variables=[
                                "Citations",
                                "Paragraphs",
                            ],
                        )
                        keyword_response = (keyword_prompt | pipeline).invoke(
                            {
                                "Citations": citations_block,
                                "Paragraphs": paragraphs_block,
                            }
                        )
                        self._append_tokens(
                            llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE
                        )
                        response_text = (
                            response_text.rstrip()
                            + "\n\n"
                            + str(keyword_response).strip()
                        )

            response_text = self._inline_citations_and_strip_blocks(response_text)
            return response_text or answer
        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            raise e

import json
import os
import re
from enum import Enum
from typing import Literal

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.retrieval.lecture.lecture_retrieval_dto import LectureRetrievalDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
from iris.vector_database.faq_schema import FaqSchema

logger = get_logger(__name__)


class InformationType(str, Enum):
    PARAGRAPHS = "PARAGRAPHS"
    FAQS = "FAQS"


class CitationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=1)
    type: Literal["L", "F"]
    entityid: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class CitationPromptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_with_markers: str
    citations: list[CitationItem]


class SummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=1)
    keyword: str
    summary: str


class SummaryPromptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summaries: list[SummaryItem]


_MARKER_RE = re.compile(r"\[(\d+)\]")


def _extract_marker_indices(answer_with_markers: str) -> set[int]:
    return {int(m.group(1)) for m in _MARKER_RE.finditer(answer_with_markers)}


def _validate_marker_coverage(resp: CitationPromptResponse) -> None:
    marker_indices = _extract_marker_indices(resp.answer_with_markers)
    citation_indices = [c.index for c in resp.citations]
    cited_set = set(citation_indices)

    if len(citation_indices) != len(cited_set):
        raise ValueError("Duplicate citation indices in citations array")

    missing = sorted(marker_indices - cited_set)
    if missing:
        raise ValueError(f"Missing citation objects for marker indices: {missing}")


def _validate_citation_semantics(resp: CitationPromptResponse) -> None:
    for c in resp.citations:
        if c.type == "F":
            if c.page is not None or c.start is not None or c.end is not None:
                raise ValueError("FAQ citations must have page/start/end = null")
        else:
            is_transcription = c.start is not None or c.end is not None
            if is_transcription:
                if c.start is None or c.end is None:
                    raise ValueError(
                        "Transcription citations must have both start and end"
                    )
            else:
                if c.page is None:
                    raise ValueError("Slide citations must have page != null")


def _validate_summary_coverage(
    summary_resp: SummaryPromptResponse, citation_resp: CitationPromptResponse
) -> None:
    needed = [c.index for c in citation_resp.citations]
    got = [s.index for s in summary_resp.summaries]
    if len(got) != len(set(got)):
        raise ValueError("Duplicate indices in summaries array")
    missing = sorted(set(needed) - set(got))
    if missing:
        raise ValueError(f"Missing summaries for citation indices: {missing}")


class CitationPipeline(SubPipeline):
    """Adds inline citations in [cite:...] format by running:
    1) citation prompt -> JSON (answer_with_markers + citations[])
    2) summary prompt -> JSON (summaries[])
    then builds inline [cite:...] deterministically.
    """

    llms: dict
    pipelines: dict

    def __init__(self):
        super().__init__(implementation_id="citation_pipeline")
        dirname = os.path.dirname(__file__)

        with open(
            os.path.join(dirname, "..", "prompts", "citation_prompt.txt"),
            "r",
            encoding="utf-8",
        ) as f:
            self.lecture_prompt_str = f.read()

        with open(
            os.path.join(dirname, "..", "prompts", "faq_citation_prompt.txt"),
            "r",
            encoding="utf-8",
        ) as f:
            self.faq_prompt_str = f.read()

        with open(
            os.path.join(
                dirname, "..", "prompts", "citation_keyword_summary_prompt.txt"
            ),
            "r",
            encoding="utf-8",
        ) as f:
            self.citation_keyword_summary_prompt_str = f.read()

        with open(
            os.path.join(dirname, "..", "prompts", "json_fix_prompt.txt"),
            "r",
            encoding="utf-8",
        ) as f:
            self.json_fix_prompt_str = f.read()

        self.tokens = []
        self.llms = {}
        self.pipelines = {}

        default_request_handler = ModelVersionRequestHandler(version="gpt-4.1-nano")
        default_llm = IrisLangchainChatModel(
            request_handler=default_request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        self.llms["default"] = default_llm
        self.pipelines["default"] = default_llm | StrOutputParser()

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

        return (
            formatted_string_lecture_page_chunks.replace("{", "{{").replace("}", "}}"),
            formatted_string_lecture_transcriptions.replace("{", "{{").replace(
                "}", "}}"
            ),
        )

    def create_formatted_faq_string(self, faqs):
        formatted_string = ""
        for faq in faqs:
            line = (
                f"FAQ ID: {faq.get(FaqSchema.FAQ_ID.value)}, "
                f"FAQ Question Title: {faq.get(FaqSchema.QUESTION_TITLE.value)}, "
                f"FAQ Answer: {faq.get(FaqSchema.QUESTION_ANSWER.value)}"
            )
            formatted_string += line
        return formatted_string.replace("{", "{{").replace("}", "}}")

    def _parse_citation_json(self, raw: str) -> CitationPromptResponse:
        data = json.loads(raw)
        resp = CitationPromptResponse.model_validate(data)
        _validate_marker_coverage(resp)
        _validate_citation_semantics(resp)
        return resp

    def _parse_summary_json(
        self, raw: str, citation_resp: CitationPromptResponse
    ) -> SummaryPromptResponse:
        data = json.loads(raw)
        resp = SummaryPromptResponse.model_validate(data)
        _validate_summary_coverage(resp, citation_resp)
        return resp

    def _fix_json_with_llm(
        self, pipeline, language_instruction: str, schema_desc: str, raw_output: str
    ) -> str:
        fix_prompt = PromptTemplate(
            template=language_instruction + self.json_fix_prompt_str,
            input_variables=["Schema", "RawOutput"],
        )
        fixed = (fix_prompt | pipeline).invoke(
            {"Schema": schema_desc, "RawOutput": raw_output}
        )
        return str(fixed).strip()

    def _retry_citation_prompt(
        self,
        pipeline,
        language_instruction: str,
        prompt_template: PromptTemplate,
        prompt_vars: dict,
        max_tries: int = 3,
    ) -> CitationPromptResponse | None:
        schema_desc = (
            'Expected JSON schema: {"answer_with_markers": <string>, "citations": '
            '[{"index": <int>, "type": "L"|"F", "entityid": <int>, "page": <int|null>, '
            '"start": <int|null>, "end": <int|null>}]}'
        )
        last_error = None
        for attempt in range(1, max_tries + 1):
            raw = str((prompt_template | pipeline).invoke(prompt_vars)).strip()
            try:
                return self._parse_citation_json(raw)
            except Exception as e:
                last_error = e
                logger.debug("Citation JSON attempt %s failed: %s", attempt, e)
                try:
                    fixed = self._fix_json_with_llm(
                        pipeline, language_instruction, schema_desc, raw
                    )
                    return self._parse_citation_json(fixed)
                except Exception as e2:
                    last_error = e2
                    continue

        logger.warning("Citation JSON failed after %s tries: %s", max_tries, last_error)
        return None

    def _retry_summary_prompt(
        self,
        pipeline,
        language_instruction: str,
        prompt_template: PromptTemplate,
        prompt_vars: dict,
        citation_resp: CitationPromptResponse,
        max_tries: int = 3,
    ) -> SummaryPromptResponse | None:
        schema_desc = (
            'Expected JSON schema: {"summaries": [{"index": <int>, "keyword": <string>, '
            '"summary": <string>}]}'
        )
        last_error = None
        for attempt in range(1, max_tries + 1):
            raw = str((prompt_template | pipeline).invoke(prompt_vars)).strip()
            try:
                return self._parse_summary_json(raw, citation_resp)
            except Exception as e:
                last_error = e
                logger.debug("Summary JSON attempt %s failed: %s", attempt, e)
                try:
                    fixed = self._fix_json_with_llm(
                        pipeline, language_instruction, schema_desc, raw
                    )
                    return self._parse_summary_json(fixed, citation_resp)
                except Exception as e2:
                    last_error = e2
                    continue

        logger.warning("Summary JSON failed after %s tries: %s", max_tries, last_error)
        return None

    def _build_inline_answer(
        self,
        citation_resp: CitationPromptResponse,
        summary_resp: SummaryPromptResponse | None,
    ) -> str:
        summary_map: dict[int, tuple[str, str]] = {}
        if summary_resp is not None:
            for s in summary_resp.summaries:
                summary_map[s.index] = (s.keyword or "", s.summary or "")

        citation_map: dict[int, dict[str, str]] = {}
        for c in citation_resp.citations:
            keyword, summ = summary_map.get(c.index, ("", ""))
            page = "" if c.page is None else str(c.page)
            start = "" if c.start is None else str(c.start)
            end = "" if c.end is None else str(c.end)

            citation_map[c.index] = {
                "type": c.type,
                "id": str(c.entityid),
                "page": page,
                "start": start,
                "end": end,
                "keyword": keyword,
                "summary": summ,
            }

        def _replace(m: re.Match) -> str:
            idx = int(m.group(1))
            data = citation_map.get(idx)
            if not data:
                return m.group(0)
            cite_type = data["type"]
            cite_id = data["id"]
            cite_page = data["page"]
            cite_start = data["start"]
            cite_end = data["end"]
            cite_keyword = data["keyword"]
            cite_summary = data["summary"]
            return (
                f"[cite:{cite_type}:{cite_id}:{cite_page}:"
                f"{cite_start}:{cite_end}:{cite_keyword}:{cite_summary}]"
            )

        return re.sub(_MARKER_RE, _replace, citation_resp.answer_with_markers)

    def _append_failure_note(self, answer: str, user_language: str) -> str:
        note_de = "Hinweis: Die Quellenangaben konnten gerade nicht generiert werden. Bitte versuche es erneut."
        note_en = "Note: Citations could not be generated right now. Please try again."
        note = note_de if user_language == "de" else note_en
        if answer.endswith("\n"):
            return answer.rstrip("\n") + "\n\n" + note
        return answer.rstrip() + "\n\n" + note

    @observe(name="Citation Pipeline")
    def __call__(
        self,
        information,
        answer: str,
        information_type: InformationType = InformationType.PARAGRAPHS,
        variant: str = "default",
        user_language: str = "en",
        **kwargs,
    ) -> str:
        paras = ""
        paragraphs_page_chunks = ""
        paragraphs_transcriptions = ""

        if variant not in self.llms:
            variant = "default"

        llm = self.llms[variant]
        pipeline = self.pipelines[variant]

        if user_language == "de":
            language_instruction = "Format all citations and references in German.\n\n"
        else:
            language_instruction = "Format all citations and references in English.\n\n"

        if information_type == InformationType.FAQS:
            paras = self.create_formatted_faq_string(information) or ""
            prompt_str = self.faq_prompt_str
            prompt = PromptTemplate(
                template=language_instruction + prompt_str,
                input_variables=["Answer", "Paragraphs"],
            )
            prompt_vars = {"Answer": answer, "Paragraphs": paras}
        else:
            paragraphs_page_chunks, paragraphs_transcriptions = (
                self.create_formatted_lecture_string(information)
            )
            paragraphs_page_chunks = paragraphs_page_chunks or ""
            paragraphs_transcriptions = paragraphs_transcriptions or ""
            prompt_str = self.lecture_prompt_str
            prompt = PromptTemplate(
                template=language_instruction + prompt_str,
                input_variables=["Answer", "Paragraphs", "TranscriptionParagraphs"],
            )
            prompt_vars = {
                "Answer": answer,
                "Paragraphs": paragraphs_page_chunks,
                "TranscriptionParagraphs": paragraphs_transcriptions,
            }

        try:
            citation_resp = self._retry_citation_prompt(
                pipeline=pipeline,
                language_instruction=language_instruction,
                prompt_template=prompt,
                prompt_vars=prompt_vars,
                max_tries=3,
            )
            self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)

            if citation_resp is None:
                return self._append_failure_note(answer, user_language)

            if not citation_resp.citations:
                return citation_resp.answer_with_markers or answer

            if information_type == InformationType.FAQS:
                paragraphs_block = (paras or "").strip()
            else:
                paragraphs_block = (
                    (paragraphs_page_chunks or "").strip()
                    + "\n\n"
                    + (paragraphs_transcriptions or "").strip()
                ).strip()

            summary_prompt = PromptTemplate(
                template=language_instruction
                + self.citation_keyword_summary_prompt_str,
                input_variables=["CitationsJSON", "Paragraphs"],
            )
            summary_vars = {
                "CitationsJSON": json.dumps(
                    [c.model_dump() for c in citation_resp.citations],
                    ensure_ascii=False,
                ),
                "Paragraphs": paragraphs_block,
            }

            summary_resp = self._retry_summary_prompt(
                pipeline=pipeline,
                language_instruction=language_instruction,
                prompt_template=summary_prompt,
                prompt_vars=summary_vars,
                citation_resp=citation_resp,
                max_tries=3,
            )
            self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)

            if summary_resp is None:
                return self._append_failure_note(answer, user_language)

            return self._build_inline_answer(citation_resp, summary_resp) or answer

        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            raise

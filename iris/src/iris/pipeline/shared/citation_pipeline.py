import json
import os
import re
import threading
from concurrent.futures import as_completed
from enum import Enum
from functools import partial

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.retrieval.lecture.lecture_retrieval_dto import LectureRetrievalDTO
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import TracedThreadPoolExecutor, observe
from iris.vector_database.faq_schema import FaqSchema

logger = get_logger(__name__)

# Matches citation blocks with fixed positional fields:
# `[cite:<type>:<entity_id>:<page>:<start>:<end>!<sequence_number>]`
# where:
# - `<type>` is `L` (lecture) or `F` (faq)
# - `<entity_id>` is the lecture unit id or faq id
# - `<page>`, `<start>`, `<end>` may be empty (`""`) if not applicable
# - `<sequence_number>` is required and is used to make the citation unique and to resolve keyword/summary enrichment
CITATION_BLOCK_WITH_SEQUENCE_PATTERN = re.compile(
    r"\[cite:([LF]):([^:\]]*):([^:\]]*):([^:\]]*):([^:\]]*)!(\d+)\]"
)
# Older formatter tests and cached intermediate responses may contain one
# redundant empty positional field before the sequence marker. Accept that
# exact legacy shape as a supplied source, but never arbitrary extra fields.
LEGACY_CITATION_BLOCK_WITH_SEQUENCE_PATTERN = re.compile(
    r"\[cite:([LF]):([^:\]]*):([^:\]]*):([^:\]]*):([^:\]]*):!(\d+)\]"
)

# Used only at the formatter trust boundary. Unlike the structured parser
# above, this deliberately captures every citation-shaped block so an invented
# or already-enriched id cannot be hidden by a narrower regular expression.
FORMATTER_CITATION_BLOCK_PATTERN = re.compile(r"\[cite:[^\[\]\r\n]+\]")

# Citation models occasionally append tags after a question mark even when the
# prompt asks for inline placement. Normalize that harmless formatting variant
# so low-support questions retain their terminal `?` contract.
QUESTION_TRAILING_CITATIONS_PATTERN = re.compile(
    r"\?(?P<leading>[ \t]+)"
    r"(?P<citations>\[cite:[LF]:[^\[\]\r\n]+\]"
    r"(?:[ \t]+\[cite:[LF]:[^\[\]\r\n]+\])*)"
)

_CITATION_TOKEN_PATTERN = re.compile(r"[a-z\u00c0-\u024f]+|\d+", re.IGNORECASE)
_ANSWER_BEARING_SOURCE_TITLE_PATTERN = re.compile(
    r"(?:\b(?:case|fall)\s*(?:number|nummer|nr\.?|#)?\s*"
    r"(?:[1-9]\d*|[ivx]+)\b|"
    r"\b(?:answer|result|solution|conclusion|classification|antwort|ergebnis|"
    r"lösung|schlussfolgerung|klassifikation)\b|"
    r"\b(?:Theta|Omega|O)\s*\(|[ΘΩ]\s*\(|"
    r"\b(?:because|therefore|hence|yields?|solves?|weil|daher|deshalb|"
    r"ergibt|löst)\b|[=→⇒])",
    re.I,
)
_CITATION_OVERLAP_STOPWORDS = {
    "about",
    "after",
    "answer",
    "could",
    "does",
    "from",
    "have",
    "material",
    "question",
    "result",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}

INDEX_CITE_TYPE = 1
INDEX_ENTITY_ID = 2
INDEX_PAGE = 3
INDEX_START = 4
INDEX_END = 5
INDEX_SEQUENCE_NUMBER = 6


def _completion_arguments_with_qa_cap() -> CompletionArguments:
    completion_args = CompletionArguments(temperature=0)
    if os.environ.get("IRIS_QA_DISABLE_PIPELINE_RETRIES") == "1":
        completion_args.max_tokens = 1000
    return completion_args


class InformationType(str, Enum):
    PARAGRAPHS = "PARAGRAPHS"
    FAQS = "FAQS"


class CitationPipeline(SubPipeline):
    """Formats answers with structured citations based on retrieved content used during answer generation."""

    llms: dict
    pipelines: dict
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="citation_pipeline")
        self._local = local
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
            dirname, "..", "prompts", "citation_keyword_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.keyword_prompt_str = file.read()
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "citation_summary_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.summary_prompt_str = file.read()
        self.tokens = []
        self._tokens_lock = threading.Lock()
        self.used_citation_numbers: list[int] = []
        self._last_citation_content_by_seq: dict[int, str] = {}
        self._last_citation_source_metadata_by_seq: dict[int, dict[str, object]] = {}

        # Create LLM variants
        self.llms = {}
        self.pipelines = {}

        pipeline_id = "citation_pipeline"
        default_model = resolve_model(pipeline_id, "default", "chat", local=local)
        advanced_model = resolve_model(pipeline_id, "advanced", "chat", local=local)

        # Default variant
        default_request_handler = LlmRequestHandler(model_id=default_model)
        default_llm = IrisLangchainChatModel(
            request_handler=default_request_handler,
            completion_args=_completion_arguments_with_qa_cap(),
        )
        self.llms["default"] = default_llm
        self.pipelines["default"] = default_llm | StrOutputParser()

        # Advanced variant
        advanced_request_handler = LlmRequestHandler(model_id=advanced_model)
        advanced_llm = IrisLangchainChatModel(
            request_handler=advanced_request_handler,
            completion_args=_completion_arguments_with_qa_cap(),
        )
        self.llms["advanced"] = advanced_llm
        self.pipelines["advanced"] = advanced_llm | StrOutputParser()

        # RequestHandler for keyword/summary (small models, separate instance per thread)
        keyword_model = resolve_model(
            pipeline_id, "default", "keyword_summary", local=local
        )
        self._keyword_summary_request_handler = LlmRequestHandler(
            model_id=keyword_model
        )
        self._keyword_summary_completion_args = _completion_arguments_with_qa_cap()

    def __repr__(self):
        return f"{self.__class__.__name__}(llms={list(self.llms.keys())})"

    def __str__(self):
        return f"{self.__class__.__name__}(llms={list(self.llms.keys())})"

    def _format_citation_part(self, value) -> str:
        return "" if value is None else str(value)

    def _build_lecture_citation_id(
        self,
        lecture_unit_id,
        page_number=None,
        start_time_sec=None,
        end_time_sec=None,
        citation_sequence_number=None,
    ) -> str:
        """
        Create a lecture citation id with stable source metadata and lookup key.

        Target format:
        `[cite:L:<lecture_unit_id>:<page_number>:<start_time_sec>:<end_time_sec>!<citation_sequence_number>]`

        The `citation_sequence_number` is the per-request running number that links a
        citation in the final answer back to its original source text.
        """
        return (
            "[cite:L:"
            f"{self._format_citation_part(lecture_unit_id)}:"
            f"{self._format_citation_part(page_number)}:"
            f"{self._format_citation_part(start_time_sec)}:"
            f"{self._format_citation_part(end_time_sec)}"
            f"!{self._format_citation_part(citation_sequence_number)}]"
        )

    def create_formatted_lecture_string(
        self, lecture_retrieval_dto: LectureRetrievalDTO
    ):
        """
        Build the serialized lecture context for the citation prompt.

        The output is a JSON array containing all usable page chunks and transcript
        segments. Each entry includes:
        - `content`: the raw text shown to the citation model
        - `id`: a structured citation id in the `[cite:L:...!<sequence_number>]` format

        The numeric suffix after `!` is a unique citation sequence number per
        request and is also used as lookup key in
        `_last_citation_content_by_seq` for later keyword/summary generation.
        """

        citation_sequence_number = 0
        self._last_citation_content_by_seq = {}
        self._last_citation_source_metadata_by_seq = {}
        lecture_page_chunks = []
        for paragraph in lecture_retrieval_dto.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            citation_sequence_number += 1
            self._last_citation_content_by_seq[citation_sequence_number] = (
                paragraph.page_text_content
            )
            self._last_citation_source_metadata_by_seq[citation_sequence_number] = {
                "kind": "slide",
                "title": paragraph.lecture_unit_name,
                "page": paragraph.display_page_number,
            }
            lecture_page_chunks.append(
                {
                    "id": self._build_lecture_citation_id(
                        paragraph.lecture_unit_id,
                        paragraph.page_number,
                        None,
                        None,
                        citation_sequence_number,
                    ),
                    "content": paragraph.page_text_content,
                }
            )

        lecture_transcriptions = []
        for paragraph in lecture_retrieval_dto.lecture_transcriptions:
            if not paragraph.segment_text:
                continue
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
            citation_sequence_number += 1
            self._last_citation_content_by_seq[citation_sequence_number] = (
                paragraph.segment_text
            )
            self._last_citation_source_metadata_by_seq[citation_sequence_number] = {
                "kind": "transcript",
                "title": paragraph.lecture_unit_name,
                "start": start_time_sec,
                "end": end_time_sec,
            }
            lecture_transcriptions.append(
                {
                    "id": self._build_lecture_citation_id(
                        paragraph.lecture_unit_id,
                        paragraph.page_number,
                        start_time_sec,
                        end_time_sec,
                        citation_sequence_number,
                    ),
                    "content": paragraph.segment_text,
                }
            )

        formatted_string = json.dumps(
            lecture_page_chunks + lecture_transcriptions,
            ensure_ascii=True,
        )
        return formatted_string

    def create_formatted_faq_string(self, faqs):
        """
        Create a formatted string from the data
        """
        formatted_faqs = []
        seq = 0
        self._last_citation_content_by_seq = {}
        for faq in faqs:
            faq_id = faq.get(FaqSchema.FAQ_ID.value)
            question = faq.get(FaqSchema.QUESTION_TITLE.value) or ""
            answer = faq.get(FaqSchema.QUESTION_ANSWER.value) or ""
            content = f"{question} {answer}".strip()
            if not content:
                continue
            seq += 1
            self._last_citation_content_by_seq[seq] = content
            formatted_faqs.append(
                {
                    "id": f"[cite:F:{faq_id}:::!{seq}]",
                    "content": content,
                }
            )

        formatted_string = json.dumps(formatted_faqs, ensure_ascii=True)
        return formatted_string

    def extract_used_citation_numbers(self, answer: str) -> list[int]:
        """
        Extracts the sequence numbers after '!' from citation blocks in the answer.
        Example matches:
        - [cite:L:lecture-id:12:0:120!3]
        - [cite:F:faq-id:::!9]
        """
        if not answer:
            return []
        numbers = []
        for match in CITATION_BLOCK_WITH_SEQUENCE_PATTERN.finditer(answer):
            numbers.append(int(match.group(INDEX_SEQUENCE_NUMBER)))
        return numbers

    def _sanitize_citation_field(self, value: str) -> str:
        if not value:
            return ""
        cleaned = value.replace(":", " -").replace("]", ")").replace("[", "(")
        cleaned = " ".join(cleaned.split())
        # Enriched fields live inside a sentence-level citation token. Sentence
        # terminators in a generated summary would otherwise make structural
        # checks treat the metadata as an extra declarative sentence.
        cleaned = re.sub(r"[.!?]+(?=\s|$)", ";", cleaned)
        return cleaned.strip(" ;")

    def _normalize_question_citation_placement(self, answer: str) -> str:
        """Move citation tags before a preceding terminal question mark."""

        def move_before_question_mark(match: re.Match) -> str:
            leading = match.group("leading")
            citations = match.group("citations")
            return f"{leading}{citations}?"

        return QUESTION_TRAILING_CITATIONS_PATTERN.sub(
            move_before_question_mark, answer
        )

    @staticmethod
    def _canonicalize_formatter_prose(value: str) -> str:
        """Normalize inconsequential whitespace without changing punctuation."""

        normalized = " ".join(value.split())
        # Removing an inline citation can leave a space before the punctuation
        # it preceded. Treat that exactly like the equally valid placement
        # after the terminal punctuation, while preserving the punctuation.
        return re.sub(r"\s+([,.;:!?])", r"\1", normalized)

    @staticmethod
    def _supplied_citation_ids(paragraphs: str) -> set[str]:
        """Return exactly the citation ids made available to the formatter."""

        try:
            sources = json.loads(paragraphs)
        except (json.JSONDecodeError, TypeError):
            return set()
        if not isinstance(sources, list):
            return set()
        return {
            citation_id
            for source in sources
            if isinstance(source, dict)
            and isinstance((citation_id := source.get("id")), str)
        }

    def _formatter_preserves_answer(
        self,
        answer: str,
        formatter_output: str,
        paragraphs: str,
    ) -> bool:
        """Accept formatter output only when it adds supplied citation ids.

        Citation placement on either side of terminal punctuation is allowed,
        as are whitespace-only differences. All words and punctuation must
        otherwise remain identical to the original answer.
        """

        citation_blocks = FORMATTER_CITATION_BLOCK_PATTERN.findall(formatter_output)
        supplied_ids = self._supplied_citation_ids(paragraphs)
        if any(citation_id not in supplied_ids for citation_id in citation_blocks):
            return False

        formatter_prose = FORMATTER_CITATION_BLOCK_PATTERN.sub("", formatter_output)
        return self._canonicalize_formatter_prose(
            formatter_prose
        ) == self._canonicalize_formatter_prose(answer)

    def _validated_formatter_output(
        self,
        answer: str,
        formatter_output: str,
        paragraphs: str,
        *,
        citation_required: bool = False,
        grounding_text: str = "",
    ) -> str:
        """Use only prose-preserving formatter output, with safe fallback."""

        if self._formatter_preserves_answer(answer, formatter_output, paragraphs):
            candidate = formatter_output
        else:
            logger.warning(
                "Citation formatter changed answer prose or emitted an unknown id; "
                "discarding formatter output"
            )
            candidate = answer
        return self._ensure_supported_citation(
            candidate,
            paragraphs,
            citation_required=citation_required,
            grounding_text=grounding_text,
        )

    @staticmethod
    def _citation_tokens(value: str) -> list[str]:
        """Normalize prose and common LaTeX notation for support comparison."""

        return [
            token.casefold()
            for token in _CITATION_TOKEN_PATTERN.findall(value.replace("\\", ""))
        ]

    @staticmethod
    def _longest_common_token_run(left: list[str], right: list[str]) -> int:
        """Return the longest contiguous shared token run using bounded memory."""

        previous = [0] * (len(right) + 1)
        longest = 0
        for left_token in left:
            current = [0] * (len(right) + 1)
            for index, right_token in enumerate(right, start=1):
                if left_token == right_token:
                    current[index] = previous[index - 1] + 1
                    longest = max(longest, current[index])
            previous = current
        return longest

    @staticmethod
    def _remove_untrusted_current_source_citations(
        answer: str,
        supplied_ids: set[str],
    ) -> str:
        """Remove model-invented citations for the source type being formatted.

        Citations of another type may already have been validated and enriched by
        the preceding citation pass (FAQ before lecture), so they are retained.
        For the current type, only an exact raw id supplied by this pass is trusted;
        enrichment happens later at this pipeline's own trust boundary.
        """

        source_types = {
            match.group(INDEX_CITE_TYPE)
            for citation_id in supplied_ids
            if (match := CITATION_BLOCK_WITH_SEQUENCE_PATTERN.fullmatch(citation_id))
            or (
                match := LEGACY_CITATION_BLOCK_WITH_SEQUENCE_PATTERN.fullmatch(
                    citation_id
                )
            )
        }

        def remove_untrusted(match: re.Match) -> str:
            citation = match.group(0)
            if citation in supplied_ids:
                return citation
            if any(
                citation.startswith(f"[cite:{source_type}:")
                for source_type in source_types
            ):
                return ""
            return citation

        cleaned = FORMATTER_CITATION_BLOCK_PATTERN.sub(remove_untrusted, answer)
        if cleaned == answer:
            return answer
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)

    def _ensure_supported_citation(
        self,
        answer: str,
        paragraphs: str,
        *,
        citation_required: bool = False,
        grounding_text: str = "",
    ) -> str:
        """Add one source id when the formatter omitted an evident citation.

        The language model remains responsible for normal citation placement.
        This conservative backstop is used only when no citation was emitted and
        the answer or its trusted grounding context has either a distinctive
        phrase or at least two meaningful terms in common with one supplied
        source. When the caller knows that the final answer is grounded in the
        supplied lecture evidence, ``citation_required`` selects the best valid
        real source even if a Socratic rewrite removed all lexical overlap. The
        normal enrichment stage still converts the selected raw id to Artemis'
        seven-field wire format.
        """

        if not answer:
            return answer
        try:
            sources = json.loads(paragraphs)
        except (json.JSONDecodeError, TypeError):
            return answer
        if not isinstance(sources, list):
            return answer

        supplied_ids = {
            citation_id
            for source in sources
            if isinstance(source, dict)
            and isinstance((citation_id := source.get("id")), str)
        }
        answer = self._remove_untrusted_current_source_citations(
            answer,
            supplied_ids,
        )
        if supplied_ids.intersection(FORMATTER_CITATION_BLOCK_PATTERN.findall(answer)):
            return answer

        answer_tokens = self._citation_tokens(answer)
        grounding_tokens = self._citation_tokens(grounding_text)
        comparison_tokens = answer_tokens + grounding_tokens
        meaningful_answer = {
            token
            for token in comparison_tokens
            if len(token) >= 4 and token not in _CITATION_OVERLAP_STOPWORDS
        }
        best_score: int | None = None
        best_citation_id: str | None = None
        first_valid_citation_id: str | None = None
        for source in sources:
            if not isinstance(source, dict):
                continue
            citation_id = source.get("id")
            content = source.get("content")
            if not isinstance(citation_id, str) or not isinstance(content, str):
                continue
            if not (
                CITATION_BLOCK_WITH_SEQUENCE_PATTERN.fullmatch(citation_id)
                or LEGACY_CITATION_BLOCK_WITH_SEQUENCE_PATTERN.fullmatch(citation_id)
            ):
                continue
            if first_valid_citation_id is None:
                first_valid_citation_id = citation_id
            source_tokens = self._citation_tokens(content)
            token_run = self._longest_common_token_run(comparison_tokens, source_tokens)
            meaningful_source = {
                token
                for token in source_tokens
                if len(token) >= 4 and token not in _CITATION_OVERLAP_STOPWORDS
            }
            overlap = len(meaningful_answer & meaningful_source)
            if token_run < 3 and overlap < 2:
                continue
            score = token_run * 3 + overlap
            if best_score is None or score > best_score:
                best_score = score
                best_citation_id = citation_id

        if best_citation_id is None and citation_required:
            best_citation_id = first_valid_citation_id
        if best_citation_id is None:
            return answer
        stripped = answer.rstrip()
        trailing = answer[len(stripped) :]
        if stripped.endswith("?"):
            return f"{stripped[:-1].rstrip()} {best_citation_id}?{trailing}"
        if stripped.endswith((".", "!")):
            return (
                f"{stripped[:-1].rstrip()} {best_citation_id}{stripped[-1]}{trailing}"
            )
        return f"{stripped} {best_citation_id}{trailing}"

    def _finalize_citations(
        self,
        response: str,
        *,
        information_type: InformationType,
        language_instruction: str,
        user_language: str,
        pointer_only_lecture: bool,
    ) -> str:
        """Enrich raw source ids, retaining a valid deterministic fallback."""

        self.used_citation_numbers = self.extract_used_citation_numbers(response)
        try:
            if pointer_only_lecture and information_type == InformationType.PARAGRAPHS:
                summaries = self._build_pointer_only_summary_map(
                    user_language=user_language,
                    used_numbers=self.used_citation_numbers,
                )
            else:
                summaries = self._build_keyword_summary_map(
                    language_instruction=language_instruction,
                    used_numbers=self.used_citation_numbers,
                )
        except Exception as enrichment_error:
            logger.error(
                "Citation enrichment failed; using source metadata only",
                exc_info=enrichment_error,
            )
            if information_type == InformationType.PARAGRAPHS:
                summaries = self._build_pointer_only_summary_map(
                    user_language=user_language,
                    used_numbers=self.used_citation_numbers,
                )
            else:
                summaries = {number: ("", "") for number in self.used_citation_numbers}
        enriched = self._replace_cite_blocks_with_keyword_summary(response, summaries)
        return self._normalize_question_citation_placement(enriched)

    def _generate_single_summary(
        self,
        language_instruction: str,
        num: int,
    ) -> str:
        """Generate a single summary for a citation number."""
        # Create thread-local LLM instance to avoid race conditions
        llm = IrisLangchainChatModel(
            request_handler=self._keyword_summary_request_handler,
            completion_args=self._keyword_summary_completion_args,
        )
        pipeline = llm | StrOutputParser()
        paragraph = self._last_citation_content_by_seq.get(num, "")
        if not paragraph.strip():
            return ""
        summary_prompt = PromptTemplate(
            template=language_instruction + self.summary_prompt_str,
            input_variables=["Paragraph"],
        )
        raw = str((summary_prompt | pipeline).invoke({"Paragraph": paragraph})).strip()
        with self._tokens_lock:
            self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
        return self._sanitize_citation_field(raw)

    def _generate_keywords_sequential(
        self,
        language_instruction: str,
        used_numbers: list[int],
    ) -> dict[int, str]:
        """Generate keywords sequentially to maintain deduplication."""
        # Create thread-local LLM instance to avoid race conditions
        llm = IrisLangchainChatModel(
            request_handler=self._keyword_summary_request_handler,
            completion_args=self._keyword_summary_completion_args,
        )
        pipeline = llm | StrOutputParser()
        keyword_prompt = PromptTemplate(
            template=language_instruction + self.keyword_prompt_str,
            input_variables=["Paragraph", "UsedKeywords"],
        )
        keywords: dict[int, str] = {}
        used_keywords: set[str] = set()
        for num in used_numbers:
            paragraph = self._last_citation_content_by_seq.get(num, "")
            if not paragraph.strip():
                keywords[num] = ""
                continue
            used_keywords_str = ", ".join(sorted(used_keywords))
            raw = str(
                (keyword_prompt | pipeline).invoke(
                    {"Paragraph": paragraph, "UsedKeywords": used_keywords_str}
                )
            ).strip()
            with self._tokens_lock:
                self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            keyword = self._sanitize_citation_field(raw)
            if keyword:
                used_keywords.add(keyword)
            keywords[num] = keyword
        return keywords

    def _build_keyword_summary_map(
        self,
        language_instruction: str,
        used_numbers: list[int],
    ) -> dict[int, tuple[str, str]]:
        # Deduplicate used_numbers while preserving order
        seen: set[int] = set()
        unique_numbers: list[int] = []
        for num in used_numbers:
            if num not in seen:
                seen.add(num)
                unique_numbers.append(num)

        # Filter out numbers with empty paragraphs
        valid_numbers = [
            num
            for num in unique_numbers
            if self._last_citation_content_by_seq.get(num, "").strip()
        ]

        if not valid_numbers:
            return {num: ("", "") for num in unique_numbers}

        with TracedThreadPoolExecutor(max_workers=len(valid_numbers) + 1) as executor:
            keyword_future = executor.submit(
                self._generate_keywords_sequential,
                language_instruction,
                valid_numbers,
            )
            summary_futures = {
                executor.submit(
                    self._generate_single_summary,
                    language_instruction,
                    num,
                ): num
                for num in valid_numbers
            }
            try:
                keywords = keyword_future.result()
            except Exception as keyword_error:
                logger.error(
                    "Citation keyword generation failed for numbers=%s",
                    valid_numbers,
                    exc_info=keyword_error,
                )
                if os.environ.get("IRIS_QA_DISABLE_PIPELINE_RETRIES") == "1":
                    raise
                keywords = {}
            summaries = {}
            for summary_future in as_completed(summary_futures):
                citation_number = summary_futures[summary_future]
                try:
                    summaries[citation_number] = summary_future.result()
                except Exception as summary_error:
                    logger.error(
                        "Citation summary generation failed for number=%s",
                        citation_number,
                        exc_info=summary_error,
                    )
                    if os.environ.get("IRIS_QA_DISABLE_PIPELINE_RETRIES") == "1":
                        raise
        result: dict[int, tuple[str, str]] = {}
        for num in unique_numbers:
            if num in valid_numbers:
                result[num] = (keywords.get(num, ""), summaries.get(num, ""))
            else:
                result[num] = ("", "")
        return result

    def _build_pointer_only_summary_map(
        self,
        user_language: str,
        used_numbers: list[int],
    ) -> dict[int, tuple[str, str]]:
        """Build faithful source pointers without exposing instructional answers."""

        german = user_language == "de"
        generic_title = "Vorlesungsquelle" if german else "Lecture source"
        result: dict[int, tuple[str, str]] = {}
        metadata_by_seq = getattr(self, "_last_citation_source_metadata_by_seq", {})
        for num in dict.fromkeys(used_numbers):
            metadata = metadata_by_seq.get(num, {})
            title = self._sanitize_citation_field(str(metadata.get("title") or ""))
            if (
                not title
                or len(title) > 80
                or _ANSWER_BEARING_SOURCE_TITLE_PATTERN.search(title)
            ):
                title = generic_title

            kind = metadata.get("kind")
            if kind == "slide":
                page = metadata.get("page")
                if page is None:
                    summary = "Vorlesungsfolie" if german else "Lecture slide"
                else:
                    prefix = "Vorlesungsfolie" if german else "Lecture slide"
                    summary = f"{prefix} {page}"
            elif kind == "transcript":
                prefix = "Vorlesungstranskript" if german else "Lecture transcript"
                start = metadata.get("start")
                end = metadata.get("end")
                if start is not None and end is not None:
                    summary = f"{prefix} {start}-{end} s"
                elif start is not None:
                    summary = (
                        f"{prefix} ab {start} s"
                        if german
                        else f"{prefix} from {start} s"
                    )
                else:
                    summary = prefix
            else:
                summary = generic_title
            result[num] = (
                title,
                self._sanitize_citation_field(summary),
            )
        return result

    def _replace_cite_blocks_with_keyword_summary(
        self, answer: str, summaries: dict[int, tuple[str, str]]
    ) -> str:
        replace_handler = partial(
            self._replace_citation_with_keyword_summary,
            summaries=summaries,
        )
        return CITATION_BLOCK_WITH_SEQUENCE_PATTERN.sub(replace_handler, answer)

    def _replace_citation_with_keyword_summary(
        self,
        citation_match: re.Match,
        summaries: dict[int, tuple[str, str]],
    ) -> str:
        cite_type = citation_match.group(INDEX_CITE_TYPE)
        entity_id = citation_match.group(INDEX_ENTITY_ID)
        page = citation_match.group(INDEX_PAGE)
        start = citation_match.group(INDEX_START)
        end = citation_match.group(INDEX_END)
        num = int(citation_match.group(INDEX_SEQUENCE_NUMBER))
        keyword, summary = summaries.get(num, ("", ""))
        return (
            f"[cite:{cite_type}:{entity_id}:{page}:{start}:{end}:{keyword}:{summary}]"
        )

    @observe(name="Citation Pipeline")
    def __call__(
        self,
        information,  #: #Union[List[dict], List[str]],
        answer: str,
        information_type: InformationType = InformationType.PARAGRAPHS,
        variant: str = "default",
        user_language: str = "en",
        pointer_only_lecture: bool = False,
        citation_required: bool = False,
        grounding_text: str = "",
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
            response_str = self._validated_formatter_output(
                answer=answer,
                formatter_output=str(response),
                paragraphs=paragraphs,
                citation_required=citation_required,
                grounding_text=grounding_text,
            )
            return self._finalize_citations(
                response_str,
                information_type=information_type,
                language_instruction=language_instruction,
                user_language=user_language,
                pointer_only_lecture=pointer_only_lecture,
            )
        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            if citation_required and information_type == InformationType.PARAGRAPHS:
                logger.warning(
                    "Using deterministic lecture citation fallback after formatter "
                    "failure"
                )
                response_str = self._ensure_supported_citation(
                    answer,
                    paragraphs,
                    citation_required=True,
                    grounding_text=grounding_text,
                )
                return self._finalize_citations(
                    response_str,
                    information_type=information_type,
                    language_instruction=language_instruction,
                    user_language=user_language,
                    pointer_only_lecture=pointer_only_lecture,
                )
            raise e

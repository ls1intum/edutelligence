import os
import re
import threading
from concurrent.futures import as_completed
from functools import partial

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import TracedThreadPoolExecutor, observe

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

# Matches simplified citation format: [cite:N]
# Used by LLM during generation, then restored to full format before enrichment
SIMPLE_CITATION_PATTERN = re.compile(r"\[cite:(\d+)\]")

INDEX_CITE_TYPE = 1
INDEX_ENTITY_ID = 2
INDEX_PAGE = 3
INDEX_START = 4
INDEX_END = 5
INDEX_SEQUENCE_NUMBER = 6


class CitationPipeline(SubPipeline):
    """Formats answers with structured citations based on retrieved content used during answer generation."""

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="citation_pipeline")
        self._local = local
        dirname = os.path.dirname(__file__)

        # Load prompts for keyword/summary enrichment
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
        self._last_citation_content_by_seq: dict[int, str] = {}

        # RequestHandler for keyword/summary (small models, separate instance per thread)
        self.keyword_summary_request_handler = ModelVersionRequestHandler(
            version="gemma3:27b" if local else "gpt-5-nano"
        )
        self._keyword_summary_completion_args = CompletionArguments(temperature=0)

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return f"{self.__class__.__name__}()"

    def _restore_simple_citations_to_full_format(
        self,
        answer: str,
        citation_content_map: dict[int, dict],
    ) -> str:
        """
        Replace simplified citation format [cite:N] with full format [cite:L:123:5::!N] or [cite:F:456:::!N].

        Args:
            answer: The answer text with simplified citations [cite:N]
            citation_content_map: Map from sequence number to citation data including full citation_id

        Returns:
            Answer with citations in full format ready for keyword/summary enrichment
        """

        def replace_simple_with_full(match: re.Match) -> str:
            seq_num = int(match.group(1))
            citation_data = citation_content_map.get(seq_num)
            if citation_data and "citation_id" in citation_data:
                return citation_data["citation_id"]
            # Fallback: keep simple format if citation not found
            return match.group(0)

        return SIMPLE_CITATION_PATTERN.sub(replace_simple_with_full, answer)

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
        return " ".join(cleaned.split())

    def _generate_single_summary(
        self,
        language_instruction: str,
        num: int,
    ) -> str:
        """Generate a single summary for a citation number."""
        # Create thread-local LLM instance to avoid race conditions
        llm = IrisLangchainChatModel(
            request_handler=self.keyword_summary_request_handler,
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
            request_handler=self.keyword_summary_request_handler,
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

        return {
            num: (keywords.get(num, ""), summaries.get(num, ""))
            for num in valid_numbers
        }

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

    def _get_language_instruction(self, user_language: str) -> str:
        """Get the language instruction prefix for prompts."""
        if user_language == "de":
            return "Format all keywords and summaries in German.\n\n"
        else:
            return "Format all keywords and summaries in English.\n\n"

    @observe(name="Citation Pipeline")
    def __call__(
        self,
        answer: str,
        citation_content_map: dict[int, dict],
        user_language: str = "en",
        **kwargs,
    ) -> str:
        """
        Enrich citations with keywords and summaries.

        The agent may use simplified citation format [cite:N] which gets restored to full format
        [cite:L:123:5::!N] before enrichment with keywords/summaries.

        Args:
            answer: The answer text with citation IDs (simplified [cite:N] or full format)
            citation_content_map: Pre-built citation map with {seq_num: {citation_id, content, ...}}
            user_language: The user's preferred language ("en" or "de")
            **kwargs: Additional keyword arguments (accepted for interface compatibility, intentionally unused)

        Returns:
            Answer with citations enriched with keywords/summaries
        """
        language_instruction = self._get_language_instruction(user_language)

        # Store content for keyword/summary generation
        self._last_citation_content_by_seq = {
            seq: data["content"] for seq, data in citation_content_map.items()
        }

        # Step 0: Restore simple citations to full format before processing
        answer = self._restore_simple_citations_to_full_format(
            answer, citation_content_map
        )

        # Step 1: Extract which citations were actually used by the agent
        used_numbers = self.extract_used_citation_numbers(answer)

        # Step 2: Generate keywords/summaries for used citations (LLM calls)
        try:
            keyword_summary_map = self._build_keyword_summary_map(
                language_instruction=language_instruction,
                used_numbers=used_numbers,
            )
            # Step 3: Replace citation IDs with enriched format
            answer = self._replace_cite_blocks_with_keyword_summary(
                answer, keyword_summary_map
            )
        except Exception:
            logger.exception(
                "Citation enrichment failed, returning citations without keyword/summary"
            )

        return answer

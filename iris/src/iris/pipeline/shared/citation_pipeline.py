import json
import os
import re
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.shared.citation_sources import (
    CitationSourceRegistry,
    cited_source_ids,
    render_citations,
    sources_for,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe

logger = get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")
_SOURCE_KEY_RE = re.compile(r"^(?:source\s*)?(\d+)$", re.IGNORECASE)


def _sanitize_citation_field(value) -> str:
    """Make a label safe inside a cite block, whose fields are separated by ":"."""
    if not value:
        return ""
    cleaned = str(value).replace(":", " -").replace("]", ")").replace("[", "(")
    return " ".join(cleaned.split())


def parse_labels(raw: str) -> dict[int, tuple[str, str]]:
    """Read the label JSON: ``{"3": {"keyword": ..., "summary": ...}}``.

    Accepts ``"Source 3"`` keys and a Markdown code fence as well. Anything unreadable yields
    no labels, so the citations are still sent, just without keyword and summary.
    """
    try:
        parsed = json.loads(_JSON_FENCE_RE.sub("", raw.strip()))
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Citation labels are not valid JSON | output_start=%r", (raw or "")[:300]
        )
        return {}
    if not isinstance(parsed, dict):
        return {}
    labels: dict[int, tuple[str, str]] = {}
    for key, value in parsed.items():
        match = _SOURCE_KEY_RE.match(str(key).strip())
        if match is None or not isinstance(value, dict):
            continue
        labels[int(match.group(1))] = (
            _sanitize_citation_field(value.get("keyword")),
            _sanitize_citation_field(value.get("summary")),
        )
    return labels


class CitationPipeline(SubPipeline):
    """Turns the source markers of a chat answer into cite blocks with keyword and summary."""

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="citation_pipeline")
        self._local = local
        prompt_file_path = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "citation_label_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.label_prompt_str = file.read()
        self.tokens = []
        self._label_model = resolve_model(
            "citation_pipeline", "default", "keyword_summary", local=local
        )

    def __repr__(self):
        return f"{self.__class__.__name__}(label_model={self._label_model})"

    def __str__(self):
        return self.__repr__()

    def _generate_labels(
        self, registry: CitationSourceRegistry, source_ids: list[int], language: str
    ) -> dict[int, tuple[str, str]]:
        sources = sources_for(registry, source_ids)
        if not sources:
            return {}
        prompt = self.label_prompt_str.format(
            language=language,
            sources="\n\n".join(
                f"Source {source.source_id}:\n{source.content}" for source in sources
            ),
        )
        llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=self._label_model),
            completion_args=CompletionArguments(temperature=0),
        )
        try:
            raw = (llm | StrOutputParser()).invoke([HumanMessage(content=prompt)])
        finally:
            if llm.tokens is not None:
                self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
        labels = parse_labels(raw)
        missing = [
            source.source_id for source in sources if source.source_id not in labels
        ]
        if missing:
            logger.warning(
                "Citation labels missing | missing=%s output_start=%r",
                missing,
                (raw or "")[:300],
            )
        return labels

    @observe(name="Citation Pipeline")
    def __call__(
        self,
        answer: str,
        registry: CitationSourceRegistry,
        language: str = "English",
        **kwargs,
    ) -> str:
        """
        Replace the source markers of an answer with cite blocks.

        :param answer: The answer with ``[src:N]`` markers written by the agent
        :param registry: The sources the tools handed out in this run
        :param language: Name of the language of the answer, such as "German"
        :return: The answer with cite blocks
        """
        self.tokens = []
        source_ids = cited_source_ids(answer, registry)
        labels: Optional[dict[int, tuple[str, str]]] = None
        if source_ids:
            try:
                labels = self._generate_labels(registry, source_ids, language)
            except Exception as e:
                logger.error(
                    "Citation labels failed; sending citations without labels",
                    exc_info=e,
                )
        return render_citations(answer, registry, labels)

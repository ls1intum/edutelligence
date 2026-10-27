import os
from typing import Optional

from pydantic import BaseModel

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from iris.llm.iris_chat_model import IrisChatModel
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

# The labels only name what a source is about; its beginning shows that. A cap keeps
# the call short when an answer cites long transcript passages.
MAX_EXCERPT_CHARS = 1500


class CitationLabel(BaseModel):
    """Keyword and summary of one cited source."""

    source: int
    keyword: str
    summary: str


class CitationLabels(BaseModel):
    """The labels of all cited sources, in one schema-enforced answer."""

    labels: list[CitationLabel]


def _sanitize_citation_field(value) -> str:
    """Make a label safe inside a cite block, whose fields are separated by ":"."""
    if not value:
        return ""
    cleaned = str(value).replace(":", " -").replace("]", ")").replace("[", "(")
    return " ".join(cleaned.split())


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
                f"Source {source.source_id}:\n"
                f"{source.content.strip()[:MAX_EXCERPT_CHARS]}"
                for source in sources
            ),
        )
        llm = IrisChatModel(
            LlmRequestHandler(model_id=self._label_model),
            CompletionArguments(temperature=0),
        )
        try:
            result = llm.structured(
                [
                    PyrisMessage(
                        sender=IrisMessageRole.USER,
                        contents=[TextMessageContentDTO(textContent=prompt)],
                    )
                ],
                CitationLabels,
            )
        finally:
            if llm.tokens is not None:
                self._append_tokens(llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
        wanted = {source.source_id for source in sources}
        labels = {
            item.source: (
                _sanitize_citation_field(item.keyword),
                _sanitize_citation_field(item.summary),
            )
            for item in result.labels
            if item.source in wanted
        }
        missing = sorted(wanted - labels.keys())
        if missing:
            logger.warning("Citation labels missing | missing=%s", missing)
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

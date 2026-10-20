import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Establish the production package import order before importing DTOs.
importlib.import_module("iris.pipeline.pipeline")

from iris.pipeline.chat import chat_pipeline  # noqa: E402
from iris.qa.loader import load_suite  # noqa: E402
from iris.qa.worker import _production_context  # noqa: E402

QA_ROOT = Path(__file__).parents[1] / "qa"


@pytest.fixture(autouse=True)
def _no_llm_backed_sub_pipelines(monkeypatch):
    """Rendering the prompts needs the pipeline object, not its LLM clients."""
    for name in (
        "SessionTitleGenerationPipeline",
        "CitationPipeline",
        "InteractionSuggestionPipeline",
        "CodeFeedbackPipeline",
        "McqGenerationPipeline",
    ):
        monkeypatch.setattr(chat_pipeline, name, MagicMock())


def _scenario(scenario_id: str):
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    return next(item for item in suite.scenarios if item.id == scenario_id)


def test_judge_sees_the_proactive_event_instructions_of_the_candidate():
    context = _production_context(_scenario("prog-build-event-moderate"))
    assert "failed to build" in context["productionTurnContext"]


def test_judge_context_is_built_for_a_lecture_with_a_viewed_position():
    context = _production_context(_scenario("lecture-slide-low"))
    assert "# Current Position" in context["productionTurnContext"]
    assert "Iris" in context["productionInstructions"]


def test_non_chat_use_cases_have_no_production_context():
    assert _production_context(_scenario("global-navigation-no-answer")) == {}

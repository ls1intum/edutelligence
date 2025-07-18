from dependency_injector import containers, providers
from pathlib import Path
from athena.container import AthenaContainer
from llm_core.container import LLMContainer

from .config import Configuration, BasicApproachConfig


class AppContainer(containers.DeclarativeContainer):
    """
    The main application container that composes and configures all other containers.
    """

    # Define which modules to scan for @inject decorators
    wiring_config = containers.WiringConfiguration(modules=[".endpoints"])

    # Inherited containers
    core = providers.Container(AthenaContainer)
    llm = providers.Container(LLMContainer)

    # Provide the path to the module's llm_config.yml
    llm.config_path.override(
        str(Path(__file__).resolve().parent.parent / "llm_config.yml")
    )

    # Provider merges the dynamic config from headers with defaults from the LLM container
    module_config = providers.Factory(
        Configuration,
        approach=providers.Factory(
            BasicApproachConfig,
            generate_feedback=llm.base_model_config,
            filter_feedback=llm.base_model_config,
            review_feedback=llm.base_model_config,
            generate_grading_instructions=llm.base_model_config,
        ),
    )

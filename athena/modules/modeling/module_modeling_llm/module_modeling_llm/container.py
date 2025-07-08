from dependency_injector import containers, providers
from pathlib import Path
from athena.containers import AthenaContainer
from llm_core.containers import LLMContainer

from .config import Configuration, BasicApproachConfig


class AppContainer(containers.DeclarativeContainer):
    """
    The main application container that composes and configures all other containers.
    """

    # Define which modules to scan for @inject decorators
    wiring_config = containers.WiringConfiguration(modules=[".endpoints"])

    # --- Inherited Containers ---
    core = providers.Container(AthenaContainer)
    llm = providers.Container(LLMContainer)

    # --- Application-specific Configuration ---
    # Provide the path to the module's llm_config.yml
    llm.config_path.override(
        str(Path(__file__).resolve().parent.parent / "llm_config.yml")
    )

    # --- Module-specific Configuration Provider ---
    # This provider merges the dynamic config from headers with defaults from the LLM container
    # This is the dependency that endpoints will request.
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

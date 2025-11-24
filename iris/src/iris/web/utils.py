from typing import Type

from fastapi import HTTPException, status

from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO
from iris.llm.llm_manager import LlmManager
from iris.pipeline.pipeline import Pipeline


def validate_pipeline_variant(
    settings: PipelineExecutionSettingsDTO, pipeline_class: Type[Pipeline]
) -> str:
    """
    Validates that the variant specified in the settings is available for the given pipeline class.

    Args:
        settings: The pipeline execution settings DTO containing variant information
        pipeline_class: The pipeline class to check variants for

    Returns:
        str: The validated variant name

    Raises:
        HTTPException: If the variant is not available or required models are missing
    """
    variant = settings.variant
    if settings.artemis_llm_selection is None:
        settings.artemis_llm_selection = "CLOUD_AI"

    # Get all variants for the pipeline
    all_variants = pipeline_class.get_variants()
    # Find the requested variant
    requested_variant = None
    for v in all_variants:
        if v.id == variant:
            requested_variant = v
            break
    # Check if variant exists
    if requested_variant is None:
        available_variant_ids = [v.id for v in all_variants]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "variant_not_available",
                "errorMessage": f'Variant "{variant}" is not available. '
                f'Available variants: {", ".join(available_variant_ids)}',
            },
        )
    # Check if required models are available
    # For variants that have required_models method, check model availability
    if hasattr(requested_variant, "required_models"):
        llm_manager = LlmManager()
        available_models = {llm.model for llm in llm_manager.entries}
        required_models = requested_variant.required_models()
        missing_models = required_models - available_models
        if missing_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "type": "models_not_available",
                    "errorMessage": f'Variant "{variant}" requires models that are not available: '
                    f'{", ".join(missing_models)}. '
                    f'Required models: {", ".join(required_models)}',
                },
            )

    return variant

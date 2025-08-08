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
        HTTPException: If the variant is not available
    """
    variant = settings.variant

    # Get available variants for the pipeline
    available_variants = [v.id for v in pipeline_class.get_variants()]

    # Validate variant
    if variant not in available_variants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "variant_not_available",
                "errorMessage": f'Variant "{variant}" is not available. '
                f"Available variants: {", ".join(available_variants)}",
            },
        )

    return variant

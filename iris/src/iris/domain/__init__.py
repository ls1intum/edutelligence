"""Public domain DTO exports without eager package initialization.

Importing a submodule such as ``iris.domain.data.message_content_dto`` must not
load chat DTOs that import ``PyrisMessage`` back from the original caller.  The
lazy exports preserve the existing ``from iris.domain import ...`` API while
keeping standalone workers free of import-order dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

# ``__getattr__`` is the standard module-level lazy-export hook name. Explicit
# aliases inside TYPE_CHECKING preserve these public re-exports for mypy.
# pylint: disable=invalid-name,useless-import-alias

if TYPE_CHECKING:
    from iris.domain.chat.chat_pipeline_execution_dto import (  # noqa: F401
        ChatPipelineExecutionDTO as ChatPipelineExecutionDTO,
    )
    from iris.domain.competency_extraction_pipeline_execution_dto import (  # noqa: F401
        CompetencyExtractionPipelineExecutionDTO as CompetencyExtractionPipelineExecutionDTO,
    )
    from iris.domain.data import (  # noqa: F401
        image_message_content_dto as image_message_content_dto,
    )
    from iris.domain.error_response_dto import (  # noqa: F401
        IrisErrorResponseDTO as IrisErrorResponseDTO,
    )
    from iris.domain.feature_dto import FeatureDTO as FeatureDTO  # noqa: F401
    from iris.domain.inconsistency_check_pipeline_execution_dto import (  # noqa: F401
        InconsistencyCheckPipelineExecutionDTO as InconsistencyCheckPipelineExecutionDTO,
    )
    from iris.domain.pipeline_execution_dto import (  # noqa: F401
        PipelineExecutionDTO as PipelineExecutionDTO,
    )
    from iris.domain.pipeline_execution_settings_dto import (  # noqa: F401
        PipelineExecutionSettingsDTO as PipelineExecutionSettingsDTO,
    )


_EXPORTS = {
    "FeatureDTO": ("iris.domain.feature_dto", "FeatureDTO"),
    "ChatPipelineExecutionDTO": (
        "iris.domain.chat.chat_pipeline_execution_dto",
        "ChatPipelineExecutionDTO",
    ),
    "CompetencyExtractionPipelineExecutionDTO": (
        "iris.domain.competency_extraction_pipeline_execution_dto",
        "CompetencyExtractionPipelineExecutionDTO",
    ),
    "image_message_content_dto": ("iris.domain.data.image_message_content_dto", None),
    "IrisErrorResponseDTO": (
        "iris.domain.error_response_dto",
        "IrisErrorResponseDTO",
    ),
    "InconsistencyCheckPipelineExecutionDTO": (
        "iris.domain.inconsistency_check_pipeline_execution_dto",
        "InconsistencyCheckPipelineExecutionDTO",
    ),
    "PipelineExecutionDTO": (
        "iris.domain.pipeline_execution_dto",
        "PipelineExecutionDTO",
    ),
    "PipelineExecutionSettingsDTO": (
        "iris.domain.pipeline_execution_settings_dto",
        "PipelineExecutionSettingsDTO",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    module = import_module(module_name)
    value = module if attribute is None else getattr(module, attribute)
    globals()[name] = value
    return value

import json
from typing import Any

from fastapi import Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from assessment_module_manager.app import app
from assessment_module_manager.authenticate import resolve_lms_url_from_secret
from assessment_module_manager.logger import logger
from assessment_module_manager.med_api import (
    ArtefactProfile,
    ArtefactType,
    DataPolicySupport,
    ErrorResponse,
    EvaluateCapabilities,
    EvaluateFeedback,
    EvaluateHealthResponse,
    EvaluateRequirements,
    EvaluateRequest,
    HealthStatus,
)
from assessment_module_manager.med_api.translation import (
    UnsupportedEvaluateRequestError,
    build_athena_feedback_suggestions_request,
    convert_athena_feedbacks_to_med_feedbacks,
)
from assessment_module_manager.module import Module, ModuleResponse, list_modules, request_to_module
from athena.schemas import ExerciseType
from .health_endpoint import is_healthy

LATEST_API_VERSION = "0.1.0"
SUPPORTED_API_VERSIONS = {LATEST_API_VERSION}
PREFERRED_EVALUATE_MODULES = {
    ExerciseType.text: "module_text_llm",
    ExerciseType.modeling: "module_modeling_llm",
}
ARTEFACT_TYPE_BY_EXERCISE_TYPE = {
    ExerciseType.text: ArtefactType.TEXT,
    ExerciseType.modeling: ArtefactType.MODEL,
}
SUPPORTED_FORMATS_BY_TYPE = {
    ExerciseType.text: ["plain", "markdown", "html"],
    ExerciseType.modeling: ["json"],
}


@app.post(
    "/evaluate",
    response_model=list[EvaluateFeedback],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request."},
        403: {"model": ErrorResponse, "description": "Forbidden."},
        406: {"model": ErrorResponse, "description": "API version not supported."},
        500: {"model": ErrorResponse, "description": "Internal server error."},
        501: {"model": ErrorResponse, "description": "Not implemented."},
        503: {"model": ErrorResponse, "description": "Service unavailable."},
    },
)
async def evaluate_submission(
    request: Request,
    response: Response,
    evaluate_request: EvaluateRequest,
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str | None = Header(None, alias="X-Request-Id"),
    x_api_version: str | None = Header(None, alias="X-Api-Version"),
):
    """Expose a small µEd /evaluate surface and translate it to Athena's feedback API."""

    logger.info(
        "Received /evaluate request request_id=%s artefact_type=%s format=%s api_version=%s",
        x_request_id,
        evaluate_request.submission.type.value,
        evaluate_request.submission.format,
        x_api_version or LATEST_API_VERSION,
    )
    resolved_version = _resolve_api_version(x_api_version)
    headers = _response_headers(x_request_id, resolved_version)

    if resolved_version is None:
        logger.warning(
            "Rejected /evaluate request request_id=%s due to unsupported API version %s",
            x_request_id,
            x_api_version,
        )
        return _error_response(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            headers=_response_headers(x_request_id, x_api_version),
            title="Version not supported",
            message=(
                f"The requested API version '{x_api_version}' is not supported. "
                f"Supported versions are: {sorted(SUPPORTED_API_VERSIONS)}."
            ),
            code="VERSION_NOT_SUPPORTED",
            details={
                "requestedVersion": x_api_version,
                "supportedVersions": sorted(SUPPORTED_API_VERSIONS),
            },
        )

    try:
        resolved_lms_url = resolve_lms_url_from_secret(authorization)
    except HTTPException as exc:
        logger.warning(
            "Rejected /evaluate request request_id=%s during authentication: %s",
            x_request_id,
            exc.detail,
        )
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            headers=headers,
            title="Forbidden",
            message=exc.detail,
            code="FORBIDDEN",
        )

    request.state.lms_url = resolved_lms_url
    logger.debug(
        "Resolved /evaluate request request_id=%s to LMS URL %s",
        x_request_id,
        resolved_lms_url,
    )

    try:
        module_type, feedback_request = build_athena_feedback_suggestions_request(
            evaluate_request,
        )
    except UnsupportedEvaluateRequestError as exc:
        logger.warning(
            "Rejected /evaluate request request_id=%s during request translation: %s",
            x_request_id,
            exc,
        )
        return _error_response(
            status_code=exc.status_code,
            headers=headers,
            title="Not implemented",
            message=str(exc),
            code=exc.code,
            details={"artefactType": evaluate_request.submission.type.value},
        )

    module = _find_evaluate_module(
        module_type=module_type,
        is_graded=bool(feedback_request["isGraded"]),
    )
    if module is None:
        logger.warning(
            "Rejected /evaluate request request_id=%s because no suitable module was found for type=%s graded=%s",
            x_request_id,
            module_type.value,
            bool(feedback_request["isGraded"]),
        )
        return _error_response(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            headers=headers,
            title="Not implemented",
            message=(
                f"No configured LLM module can serve /evaluate for "
                f"{evaluate_request.submission.type.value} submissions."
            ),
            code="NOT_IMPLEMENTED",
            details={"artefactType": evaluate_request.submission.type.value},
        )

    logger.info(
        "Dispatching /evaluate request request_id=%s to module=%s type=%s graded=%s lms_url=%s",
        x_request_id,
        module.name,
        module.type.value,
        bool(feedback_request["isGraded"]),
        resolved_lms_url,
    )
    module_response = await request_to_module(
        module=module,
        headers=_build_module_headers(
            request,
            resolved_version,
            x_request_id,
            resolved_lms_url,
        ),
        path="/feedback_suggestions",
        lms_url=resolved_lms_url,
        data=feedback_request,
        method="POST",
    )
    logger.debug(
        "Received module response for /evaluate request request_id=%s from module=%s status=%s",
        x_request_id,
        module.name,
        module_response.status,
    )
    if module_response.status != status.HTTP_200_OK:
        return _map_module_error(module_response, headers)

    try:
        med_feedbacks = convert_athena_feedbacks_to_med_feedbacks(
            artefact_type=evaluate_request.submission.type,
            submission_format=evaluate_request.submission.format,
            athena_feedbacks=module_response.data,
        )
    except (UnsupportedEvaluateRequestError, ValueError, TypeError) as exc:
        logger.exception(
            "Failed to translate Athena feedback response for /evaluate request request_id=%s module=%s",
            x_request_id,
            module.name,
        )
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers=headers,
            title="Internal server error",
            message=f"Failed to translate the Athena feedback response: {exc}",
            code="INTERNAL_ERROR",
            details={"moduleName": module.name},
        )

    for header_name, header_value in headers.items():
        response.headers[header_name] = header_value
    logger.info(
        "Completed /evaluate request request_id=%s with %s feedback items from module=%s",
        x_request_id,
        len(med_feedbacks),
        module.name,
    )
    return med_feedbacks


@app.get(
    "/evaluate/health",
    response_model=EvaluateHealthResponse,
    responses={
        406: {"model": ErrorResponse, "description": "API version not supported."},
        503: {"model": ErrorResponse, "description": "Service unavailable."},
    },
)
async def get_evaluate_health(
    response: Response,
    x_request_id: str | None = Header(None, alias="X-Request-Id"),
    x_api_version: str | None = Header(None, alias="X-Api-Version"),
):
    """Report health and capabilities for the manager-side µEd evaluate endpoint."""

    resolved_version = _resolve_api_version(x_api_version)
    headers = _response_headers(x_request_id, resolved_version)

    if resolved_version is None:
        return _error_response(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            headers=_response_headers(x_request_id, x_api_version),
            title="Version not supported",
            message=(
                f"The requested API version '{x_api_version}' is not supported. "
                f"Supported versions are: {sorted(SUPPORTED_API_VERSIONS)}."
            ),
            code="VERSION_NOT_SUPPORTED",
            details={
                "requestedVersion": x_api_version,
                "supportedVersions": sorted(SUPPORTED_API_VERSIONS),
            },
        )

    selected_modules = _selected_evaluate_modules()
    healthy_modules: dict[ExerciseType, Module] = {}
    for module_type, module in selected_modules.items():
        health_result = is_healthy(module)
        if hasattr(health_result, "__await__"):
            health_result = await health_result
        if health_result:
            healthy_modules[module_type] = module

    health_response = EvaluateHealthResponse(
        status=_evaluate_health_status(
            configured_modules=selected_modules,
            healthy_modules=healthy_modules,
        ),
        message=_evaluate_health_message(
            configured_modules=selected_modules,
            healthy_modules=healthy_modules,
        ),
        version=app.version,
        requirements=EvaluateRequirements(
            requires_authorization_header=True,
            requires_llm_configuration=False,
            requires_llm_credential_proxy=False,
        ),
        capabilities=EvaluateCapabilities(
            supports_evaluate=bool(healthy_modules),
            supports_pre_submission_feedback=any(
                module.supports_non_graded_feedback_requests
                for module in healthy_modules.values()
            ),
            supports_formative_feedback=any(
                module.supports_non_graded_feedback_requests
                for module in healthy_modules.values()
            ),
            supports_summative_feedback=any(
                module.supports_graded_feedback_requests
                for module in healthy_modules.values()
            ),
            supports_data_policy=DataPolicySupport.NOT_SUPPORTED,
            supported_artefact_profiles=_supported_artefact_profiles(healthy_modules),
            supported_languages=_supported_languages(healthy_modules),
            supported_api_versions=sorted(SUPPORTED_API_VERSIONS),
        ),
    )

    for header_name, header_value in headers.items():
        response.headers[header_name] = header_value
    return health_response


def _resolve_api_version(requested_version: str | None) -> str | None:
    if requested_version is None:
        return LATEST_API_VERSION
    if requested_version in SUPPORTED_API_VERSIONS:
        return requested_version
    return None


def _response_headers(
    x_request_id: str | None,
    x_api_version: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if x_request_id:
        headers["X-Request-Id"] = x_request_id
    if x_api_version:
        headers["X-Api-Version"] = x_api_version
    return headers


def _build_module_headers(
    request: Request,
    x_api_version: str,
    x_request_id: str | None,
    lms_url: str,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "X-Api-Version": x_api_version,
    }
    if x_request_id:
        headers["X-Request-Id"] = x_request_id

    for header_name in (
        "X-Module-Config",
    ):
        header_value = request.headers.get(header_name)
        if header_value:
            headers[header_name] = header_value
    headers["X-Server-URL"] = lms_url
    return headers


def _find_evaluate_module(module_type: ExerciseType, is_graded: bool) -> Module | None:
    return _pick_evaluate_module(
        [
            module
            for module in list_modules()
            if module.type == module_type
            and _supports_feedback_generation(module, is_graded)
            and "llm" in module.name
        ],
        module_type=module_type,
    )


def _supports_feedback_generation(module: Module, is_graded: bool) -> bool:
    if is_graded:
        return module.supports_graded_feedback_requests
    return module.supports_non_graded_feedback_requests


def _pick_evaluate_module(
    modules: list[Module],
    *,
    module_type: ExerciseType,
) -> Module | None:
    preferred_name = PREFERRED_EVALUATE_MODULES.get(module_type)
    if preferred_name is not None:
        for module in modules:
            if module.name == preferred_name:
                return module
    return modules[0] if modules else None


def _selected_evaluate_modules() -> dict[ExerciseType, Module]:
    selected: dict[ExerciseType, Module] = {}
    for module_type in PREFERRED_EVALUATE_MODULES:
        candidates = [
            module
            for module in list_modules()
            if module.type == module_type
            and "llm" in module.name
            and (
                module.supports_graded_feedback_requests
                or module.supports_non_graded_feedback_requests
            )
        ]
        selected_module = _pick_evaluate_module(candidates, module_type=module_type)
        if selected_module is not None:
            selected[module_type] = selected_module
    return selected


def _evaluate_health_status(
    *,
    configured_modules: dict[ExerciseType, Module],
    healthy_modules: dict[ExerciseType, Module],
) -> HealthStatus:
    if not configured_modules or not healthy_modules:
        return HealthStatus.UNAVAILABLE
    if len(healthy_modules) == len(configured_modules):
        return HealthStatus.OK
    return HealthStatus.DEGRADED


def _evaluate_health_message(
    *,
    configured_modules: dict[ExerciseType, Module],
    healthy_modules: dict[ExerciseType, Module],
) -> str:
    if not configured_modules:
        return "Evaluate service unavailable. No evaluate modules are configured."
    if not healthy_modules:
        return "Evaluate service unavailable. No configured evaluate module is currently healthy."
    if len(healthy_modules) == len(configured_modules):
        return "Evaluate service healthy."
    return "Evaluate service degraded. Some configured evaluate modules are unavailable."


def _supported_artefact_profiles(
    healthy_modules: dict[ExerciseType, Module],
) -> list[ArtefactProfile] | None:
    profiles = [
        ArtefactProfile(
            type=ARTEFACT_TYPE_BY_EXERCISE_TYPE[module_type],
            supported_formats=SUPPORTED_FORMATS_BY_TYPE.get(module_type),
        )
        for module_type in healthy_modules
        if module_type in ARTEFACT_TYPE_BY_EXERCISE_TYPE
    ]
    return profiles or None


def _supported_languages(
    healthy_modules: dict[ExerciseType, Module],
) -> list[str] | None:
    if ExerciseType.text in healthy_modules:
        return ["en", "de"]
    return None


def _map_module_error(
    module_response: ModuleResponse[Any, Any],
    headers: dict[str, str],
) -> JSONResponse:
    message = _extract_error_message(module_response.data)
    logger.warning(
        "Module %s returned error status=%s message=%s",
        module_response.module_name,
        module_response.status,
        message,
    )
    if module_response.status in {status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY}:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            headers=headers,
            title="Invalid request",
            message=message or "The translated Athena request was rejected by the target module.",
            code="BAD_REQUEST",
            details={"moduleName": module_response.module_name},
        )
    if module_response.status in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            headers=headers,
            title="Forbidden",
            message=message or "The target module rejected the request.",
            code="FORBIDDEN",
            details={"moduleName": module_response.module_name},
        )
    if module_response.status == status.HTTP_503_SERVICE_UNAVAILABLE:
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers=headers,
            title="Service unavailable",
            message=message or "The target module is currently unavailable.",
            code="SERVICE_UNAVAILABLE",
            details={"moduleName": module_response.module_name},
        )
    if module_response.status == status.HTTP_501_NOT_IMPLEMENTED:
        return _error_response(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            headers=headers,
            title="Not implemented",
            message=message or "The target module does not implement the requested functionality.",
            code="NOT_IMPLEMENTED",
            details={"moduleName": module_response.module_name},
        )
    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers=headers,
        title="Internal server error",
        message=message or "The target module returned an unexpected response.",
        code="INTERNAL_ERROR",
        details={"moduleName": module_response.module_name},
    )


def _extract_error_message(data: Any) -> str | None:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail, ensure_ascii=True, sort_keys=True)
        message = data.get("message")
        if isinstance(message, str):
            return message
        return json.dumps(data, ensure_ascii=True, sort_keys=True)
    return None


def _error_response(
    *,
    status_code: int,
    headers: dict[str, str],
    title: str,
    message: str,
    code: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        title=title,
        message=message,
        code=code,
        details=details,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
        headers=headers,
    )

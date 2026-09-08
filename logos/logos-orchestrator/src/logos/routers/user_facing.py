"""User-facing endpoints: OpenAI-compatible model listing, audio, proxies, jobs.

This router holds the /v1/{path:path} catch-all, so logos.main includes it
last — a router included after the catch-all would be unreachable for any
/v1/* path.
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

import logos.main as _main
from logos.auth import authenticate_api_key
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbmodules import JobStatus
from logos.errors import coerce_upstream_error
from logos.jobs.job_service import JobService
from logos.logosnode_snapshot import _resolve_requested_model_name
from logos.main import _model_context_fields, _served_context_window_stats, handle_sync_request, submit_job_request

logger = logging.getLogger("LogosLogger")

router = APIRouter()

_SERVER_START_TIME = int(time.time())


@router.get("/v1/models", tags=["user-facing"])
@router.get("/openai/models", tags=["user-facing"], include_in_schema=False)
async def list_models(request: Request):
    """
    List models accessible to the authenticated user (OpenAI-compatible).

    Also served under /openai/models: the /openai prefix mirrors /v1, and the
    POST catch-all alias cannot answer this GET.

    Returns an OpenAI-compatible response listing all models the user's
    current API key has access to (Union of Team models and specific API Key models).
    Stored aliases of an accessible model are listed as additional model ids
    right after their model, so logical names (e.g. 'local-most-powerful')
    can be discovered and used directly in requests.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models spec.
    """
    auth = authenticate_api_key(dict(request.headers))

    with DBManager() as db:
        models = db.get_models_for_api_key(auth.api_key_id)

    stats = _served_context_window_stats()
    data = []
    for model in models:
        name = model["name"]
        # Aliases resolve to the same model, so they carry the context-window
        # fields of the lanes serving it.
        data.append(
            {
                "id": name,
                "object": "model",
                "created": _SERVER_START_TIME,
                "owned_by": "logos",
                **_model_context_fields(stats.get(name)),
            }
        )
        for alias in model.get("aliases") or []:
            data.append(
                {
                    "id": alias,
                    "object": "model",
                    "created": _SERVER_START_TIME,
                    "owned_by": "logos",
                    **_model_context_fields(stats.get(name)),
                }
            )

    return JSONResponse(content={"object": "list", "data": data})


@router.get("/v1/models/{model_id:path}", tags=["user-facing"])
@router.get("/openai/models/{model_id:path}", tags=["user-facing"], include_in_schema=False)
async def retrieve_model(model_id: str, request: Request):
    """
    Retrieve a single model by name (OpenAI-compatible).

    Verifies the authenticated user has access to the requested model
    through their combined (Team + API Key) model permissions.

    Params:
        model_id: The model name (used as the OpenAI-style model id).
        request: Incoming request.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models/{model} spec.

    Raises:
        HTTPException(404): Model not found or user lacks access.
    """
    auth = authenticate_api_key(dict(request.headers))

    with DBManager() as db:
        model = db.get_model_for_api_key(auth.api_key_id, model_id)
        if not model:
            models = db.get_models_for_api_key(auth.api_key_id)
            canonical_model_name = _resolve_requested_model_name(model_id, models)
            if canonical_model_name is not None:
                model = next(
                    (entry for entry in models if entry.get("name") == canonical_model_name),
                    None,
                )

    if not model:
        raise HTTPException(status_code=404, detail="Model not found or access denied")

    stats = _served_context_window_stats()
    return JSONResponse(
        content={
            "id": model["name"],
            "object": "model",
            "created": _SERVER_START_TIME,
            "owned_by": "logos",
            **_model_context_fields(stats.get(model["name"])),
        }
    )


def _resolve_accessible_model_name(api_key_id: int, model_id: str) -> Optional[str]:
    """Canonical name of ``model_id`` if this key may use it, else None.

    Shared by the model endpoints below: they all have to accept the same
    aliases (stored alternative names, planner-sanitized underscores, case
    differences) and all have to refuse a model the key has no permission for.
    """
    with DBManager() as db:
        model = db.get_model_for_api_key(api_key_id, model_id)
        if model:
            return model["name"]
        models = db.get_models_for_api_key(api_key_id)
        return _resolve_requested_model_name(model_id, models)


@router.post("/v1/models/{model_id:path}/warmup", tags=["user-facing"])
@router.post("/openai/models/{model_id:path}/warmup", tags=["user-facing"], include_in_schema=False)
async def warmup_model(model_id: str, request: Request):
    """Tell the planner a model is about to be used, and return immediately.

    A coding assistant asks for the model list when it starts and then sits
    idle while the developer reads the terminal — the first real request lands
    seconds later, and pays for a cold load it could have overlapped with that
    pause. This turns the startup into a hint.

    It is a *hint*, not a reservation: it records the same latent demand the
    scheduler records when classification prefers a model it did not get, and
    wakes the planner cycle early. The planner still decides what to load using
    its own fairness rules, so a warmup can never evict a lane that real
    traffic is using, and a burst of them coalesces into one extra cycle. That
    is also what keeps it from being a way to make the cluster thrash: the most
    an authenticated caller can do is raise a model it already has access to
    slightly in the queue of things worth loading.

    Deliberately not "send a tiny request": that bills the caller, occupies a
    slot, and returns a completion nobody wanted.
    """
    auth = authenticate_api_key(dict(request.headers))
    model_name = _resolve_accessible_model_name(auth.api_key_id, model_id)
    if model_name is None:
        raise HTTPException(status_code=404, detail="Model not found or access denied")

    stats = _served_context_window_stats().get(model_name) or {}
    # A reported window means some lane is serving the model right now, which is
    # the closest thing to "ready" this endpoint can answer without asking every
    # worker. Already-warm models still record the hint: it keeps the model from
    # decaying out of the planner's demand view while a session is open.
    already_serving = bool(stats.get("current_min"))

    accepted = False
    if _main._demand_tracker is not None:
        _main._demand_tracker.record_latent_demand(model_name)
        accepted = True
    if _main._capacity_planner is not None:
        # announce_upcoming_use, not hint_capacity_needed: the hint only wakes
        # the cycle early, and the demand increment above cannot survive the
        # per-cycle decay that runs before the planner evaluates it, so on its
        # own a warmup would wake a cycle that then decides to do nothing —
        # which is exactly what it did. The announcement is what lets the
        # planner cold-load on VRAM that is free anyway.
        _main._capacity_planner.announce_upcoming_use(model_name)
        accepted = True

    logger.info(
        "Warmup requested for model=%s (already serving: %s, hint accepted: %s)",
        model_name,
        already_serving,
        accepted,
    )
    return JSONResponse(
        status_code=202,
        content={
            "model": model_name,
            "status": "serving" if already_serving else "preparing",
            "hint_accepted": accepted,
            **_model_context_fields(stats),
        },
    )


_AUDIO_BASE_PROPERTIES = {
    "file": {"type": "string", "format": "binary"},
    "model": {"type": "string"},
    "prompt": {"type": "string"},
    "response_format": {
        "type": "string",
        "enum": ["json", "text", "srt", "verbose_json", "vtt"],
        "default": "json",
    },
    "temperature": {"type": "number", "minimum": 0, "maximum": 1},
}

_TRANSCRIPTION_UPLOAD_REQUEST_SCHEMA = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "model"],
                "properties": {
                    **_AUDIO_BASE_PROPERTIES,
                    "language": {"type": "string", "description": "ISO-639-1 language code"},
                    "timestamp_granularities[]": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["word", "segment"]},
                        "description": "whisper-1 with response_format=verbose_json only",
                    },
                    "stream": {
                        "type": "boolean",
                        "default": False,
                        "description": "Ignored by whisper-1; supported by newer transcription models",
                    },
                },
            }
        }
    },
}

_TRANSLATION_UPLOAD_REQUEST_SCHEMA = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "model"],
                "description": "OpenAI translations currently support the whisper-1 model",
                "properties": _AUDIO_BASE_PROPERTIES,
            }
        }
    },
}

_AUDIO_UPLOAD_RESPONSES = {
    200: {
        "description": "Transcription result in the requested response format",
        "content": {
            "application/json": {},
            "text/plain": {},
            "text/vtt": {},
            "application/x-subrip": {},
            "text/event-stream": {},
        },
    }
}


@router.post(
    "/v1/audio/transcriptions",
    tags=["audio"],
    summary="Create an audio transcription",
    response_class=Response,
    responses=_AUDIO_UPLOAD_RESPONSES,
    openapi_extra={"requestBody": _TRANSCRIPTION_UPLOAD_REQUEST_SCHEMA},
)
async def create_audio_transcription(request: Request):
    """Transcribe an uploaded audio file through an authorized model."""
    return await handle_sync_request("v1/audio/transcriptions", request)


@router.post(
    "/v1/audio/translations",
    tags=["audio"],
    summary="Create an English audio translation",
    response_class=Response,
    responses=_AUDIO_UPLOAD_RESPONSES,
    openapi_extra={"requestBody": _TRANSLATION_UPLOAD_REQUEST_SCHEMA},
)
async def create_audio_translation(request: Request):
    """Transcribe and translate an uploaded audio file into English."""
    return await handle_sync_request("v1/audio/translations", request)


@router.post("/v1/{path:path}", tags=["user-facing"])
async def logos_service_sync(path: str, request: Request):
    """
    Dynamic proxy for OpenAI-compatible API endpoints (/v1/*).
    Supports both PROXY and RESOURCE modes with streaming.

    POST only: every proxied operation (chat/completions, completions,
    responses, embeddings, ...) is a POST in the upstream APIs. Other methods
    get a proper 405 from the router instead of the misleading
    "400 Invalid JSON body" the body parser used to raise on body-less GETs.
    """
    return await handle_sync_request(f"v1/{path}", request)


@router.post("/v2/{path:path}", tags=["user-facing"])
async def logos_service_v2_sync(path: str, request: Request):
    """
    Dynamic proxy for Cohere-compatible API endpoints (/v2/embed, /v2/rerank).
    """
    return await handle_sync_request(f"v2/{path}", request)


@router.post(
    "/openai/{path:path}",
    tags=["user-facing"],
)
async def logos_service_long_sync(request: Request, path: str = None):
    """
    Dynamic proxy for LLM API endpoints (OpenAI-compatible paths).
    Supports two modes:
    - PROXY MODE: Direct forwarding to provider (no classification/scheduling)
    - RESOURCE MODE: Classification + scheduling with SDI-aware pipeline

    :param request: Request object containing headers, body, and client metadata
    :param path: API endpoint path (e.g., 'chat/completions', 'completions', 'embeddings')
    :return: StreamingResponse for streaming requests, JSONResponse for synchronous requests
    """
    return await handle_sync_request(f"v1/{path}", request)


# vLLM non-prefixed endpoints (not part of OpenAI API spec, but user-facing).
# These are canonical paths for pooling, scoring, reranking, and tokenization.
async def _handle_vllm_native(request: Request):
    """Forward to vLLM using the original request path."""
    path = request.url.path.lstrip("/")
    return await handle_sync_request(path, request)


for _vllm_path in ("/pooling", "/score", "/rerank", "/tokenize", "/detokenize"):
    router.add_api_route(
        _vllm_path,
        _handle_vllm_native,
        methods=["POST"],
        tags=["user-facing"],
        name=f"vllm_native_{_vllm_path.lstrip('/')}",
    )


@router.post(
    "/jobs/v1/{path:path}",
    tags=["user-facing"],
)
async def logos_service_async(path: str, request: Request):
    """
    Async job-based proxy for long running/low-priority requests.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        202 with job metadata; poll /jobs/{id} for result.
    """
    return await submit_job_request(f"v1/{path}", request)


@router.post(
    "/jobs/v2/{path:path}",
    tags=["user-facing"],
)
async def logos_service_v2_async(path: str, request: Request):
    """Async job-based proxy for Cohere-compatible endpoints."""
    return await submit_job_request(f"v2/{path}", request)


@router.post(
    "/jobs/openai/{path:path}",
    tags=["user-facing"],
)
async def logos_service_long_async(path: str, request: Request):
    """
    Async job-based proxy for OpenAI-compatible, long running/low-priority requests.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        202 with job metadata; poll /jobs/{id} for result.
    """
    return await submit_job_request(f"v1/{path}", request)


@router.get("/jobs/{job_id}", tags=["user-facing"])
async def get_job_status(job_id: int, request: Request):
    """
    Return current state of a submitted job, including result or error when finished.
    Uses team-based authorization - you can only view jobs created by your current team.
    Logos Admins can view all jobs.
    """
    auth = authenticate_api_key(dict(request.headers))

    job = JobService.fetch(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Authorization checks
    job_api_key_id = job.get("api_key_id")
    job_team_id = job.get("team_id")

    with DBManager() as db:
        user_info = db.get_user_by_api_key(auth.key_value)
        is_admin = user_info and user_info.get("role") == "logos_admin"

    if not is_admin:
        if job_api_key_id != auth.api_key_id:
            raise HTTPException(status_code=403, detail="Not authorized to access this job")
        if job_team_id != auth.team_id:
            raise HTTPException(status_code=403, detail="Job belongs to a different team.")

    return_payload = {
        "job_id": job_id,
        "status": job["status"],
        "result": (job["result_payload"] if job["status"] == JobStatus.SUCCESS.value else None),
        "error": (job["error_message"] if job["status"] == JobStatus.FAILED.value else None),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "team_id": job_team_id,
    }

    # When a completed job has a non-2xx upstream status code, surface the
    # error body with the correct HTTP status so OpenAI-spec clients behave
    # correctly (e.g. don't blind-retry a 400 context-length error).
    if job["status"] == JobStatus.SUCCESS.value:
        result_payload = job.get("result_payload") or {}
        job_status_code = result_payload.get("status_code") if isinstance(result_payload, dict) else None
        if isinstance(job_status_code, int) and job_status_code >= 400:
            job_data = result_payload.get("data") or {}
            corrected_sc, error_body = coerce_upstream_error(job_status_code, job_data)
            return JSONResponse(
                content={**return_payload, "result": None, "error": error_body},
                status_code=corrected_sc,
            )

    if job["status"] == JobStatus.FAILED.value and job.get("error_message"):
        # Wrap plain-string failure message in OpenAI error shape
        _, error_body = coerce_upstream_error(500, {"error": job["error_message"]})
        return JSONResponse(content={**return_payload, "error": error_body}, status_code=500)

    return return_payload

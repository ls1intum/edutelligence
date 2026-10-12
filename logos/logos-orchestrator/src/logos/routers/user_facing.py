"""User-facing endpoints: OpenAI-compatible model listing, audio, proxies, jobs.

This router holds the /v1/{path:path} catch-all, so logos.main includes it
last — a router included after the catch-all would be unreachable for any
/v1/* path.
"""

import asyncio
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

import logos.main as _main
from logos.anthropic_compat import translate_error
from logos.anthropic_compat import web_search as server_web_search
from logos.auth import authenticate_api_key
from logos.batch_api import handle_batch_api_request
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.dbrequest import SystemOneRequest, WebSearchRequest
from logos.decision import DecisionError, answer_system_one
from logos.errors import coerce_upstream_error
from logos.jobs.job_service import JobService
from logos.logosnode_snapshot import _resolve_requested_model_name, claude_visible_id
from logos.main import _model_context_fields, _served_context_window_stats, handle_sync_request, submit_job_request
from logos.responses import get_client_ip
from logos.web_search import SearchUnavailable, search_web

logger = logging.getLogger("LogosLogger")

router = APIRouter()

_SERVER_START_TIME = int(time.time())

# RFC 3339 rendering of the start time, for the Anthropic models shape whose
# ``created_at`` is a datetime string (the OpenAI shape uses the bare epoch int).
_SERVER_START_TIME_ISO = datetime.fromtimestamp(_SERVER_START_TIME, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# The header every Anthropic SDK / Claude Code request carries; OpenAI clients
# never send it. It is how one shared GET /v1/models answers both dialects.
_ANTHROPIC_VERSION_HEADER = "anthropic-version"


def _anthropic_entries(
    models: list[dict], stats: dict, other_models: Optional[list[dict]] = None
) -> list[tuple[str, str, Optional[str]]]:
    """(id, model_name, description) rows for the Anthropic listing.

    One row per accessible model, aliases left out. ``model_name`` is the
    canonical name the context-window stats are keyed by.

    Claude Code drops every gateway model whose id has no "claude"/"anthropic"
    in it, so each id is listed as ``claude-<name>`` (see ``claude_visible_id``)
    and only in that form. The request path strips the prefix again, and the
    plain name and the aliases keep resolving there. A prefixed id that would
    resolve to a different model is never advertised. ``other_models`` widens that
    check to models the key cannot see: the proxy resolver searches every model
    for administrator keys, so a hidden ``claude-foo`` would still capture it.
    """
    visible = {model["name"] for model in models}
    candidates = models + [model for model in other_models or [] if model["name"] not in visible]
    entries: list[tuple[str, str, Optional[str]]] = []
    for model in models:
        name = model["name"]
        entry_id = claude_visible_id(name) or name
        if entry_id != name and _resolve_requested_model_name(entry_id, candidates) != name:
            # Another model or alias already owns claude-<name> (``foo`` next to
            # ``claude-foo``): advertising it would select that one instead, so
            # this model is listed under its own name.
            entry_id = name
        # The picker shows display_name, so the prefixed id keeps the plain name there.
        entries.append((entry_id, name, model.get("description") or name))
    return entries


def _anthropic_model_info(model_id: str, model_name: str, description: Optional[str], stats: dict) -> dict:
    """One ``BetaModelInfo`` object for the Anthropic models listing."""
    fields = _model_context_fields(stats.get(model_name))
    # The guaranteed window a request is sure to get (the smallest served),
    # falling back to the widest the model is ever served with, else unknown.
    max_input = fields.get("max_model_len") or fields.get("max_model_len_overall")
    return {
        "type": "model",
        "id": model_id,
        "display_name": description or model_id,
        "created_at": _SERVER_START_TIME_ISO,
        "max_input_tokens": max_input,
        "max_tokens": None,
        "capabilities": None,
        "allowed_fallback_models": None,
    }


def _parse_models_limit(raw: Optional[str]) -> Optional[int]:
    """The ``limit`` query param clamped to the API's 1..1000 range, or None."""
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, min(value, 1000))


def _anthropic_models_response(
    models: list[dict],
    stats: dict,
    limit: Optional[int],
    after_id: Optional[str],
    other_models: Optional[list[dict]] = None,
) -> JSONResponse:
    """The Anthropic ``GET /v1/models`` envelope over the accessible models.

    Logos lists are small, so ``limit`` defaults to "everything" (``has_more``
    stays false) rather than the Anthropic API's 20 — a client that does not
    paginate would otherwise silently miss models. ``after_id`` is a cursor into
    the (stable, id-ordered) listing.
    """
    entries = _anthropic_entries(models, stats, other_models)
    if after_id:
        for index, (entry_id, _, _) in enumerate(entries):
            if entry_id == after_id:
                entries = entries[index + 1 :]
                break
        # A stale/unknown cursor starts the list rather than erroring.
    total = len(entries)
    page = entries[:limit] if limit is not None else entries
    data = [
        _anthropic_model_info(entry_id, model_name, description, stats) for entry_id, model_name, description in page
    ]
    return JSONResponse(
        content={
            "data": data,
            "first_id": data[0]["id"] if data else None,
            "last_id": data[-1]["id"] if data else None,
            "has_more": len(page) < total,
        }
    )


@router.get("/v1/models", tags=["user-facing"])
@router.get("/openai/models", tags=["user-facing"], include_in_schema=False)
async def list_models(request: Request):
    """
    List models accessible to the authenticated user (OpenAI-compatible).

    Also served under /openai/models: the /openai prefix mirrors /v1, and the
    POST catch-all alias cannot answer this GET.

    Answers in the dialect the caller speaks:

    * With the mandatory ``anthropic-version`` header (every Anthropic SDK and
      Claude Code request carries it) the response is the Anthropic models
      shape (``data`` of ``BetaModelInfo`` plus ``first_id``/``last_id``/
      ``has_more``), so a Messages client can discover the models it may use
      and switch between them on demand.
    * Otherwise it is the OpenAI-compatible response listing all models the
      user's current API key has access to (Union of Team models and specific
      API Key models).

    Stored aliases of an accessible model are listed as additional model ids
    right after their model, so logical names (e.g. 'local-most-powerful')
    can be discovered and used directly in requests. An alias that belongs to
    more than one accessible model is omitted: it cannot be resolved, so
    advertising it would promise a model id that retrieval rejects.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models spec, or the Anthropic
        models shape when the caller sends ``anthropic-version``.
    """
    auth = authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))

    anthropic_shape = _ANTHROPIC_VERSION_HEADER in request.headers
    with DBManager() as db:
        models = db.get_models_for_api_key(auth.api_key_id)
        # Only administrator keys resolve against every model (the same test
        # as proxy mode in main.py); for any other key a hidden model cannot
        # capture a prefixed id, so it must not hide a usable one.
        admin_scope = auth.role in ("logos_admin", "app_admin")
        other_models = db.get_all_model_names_with_aliases() if anthropic_shape and admin_scope else None

    stats = _served_context_window_stats()

    if anthropic_shape:
        return _anthropic_models_response(
            models,
            stats,
            _parse_models_limit(request.query_params.get("limit")),
            request.query_params.get("after_id"),
            other_models,
        )

    # An alias that (case-insensitively) belongs to more than one accessible
    # model cannot be resolved at request time, so it is not advertised.
    alias_owners: dict[str, set[str]] = {}
    for model in models:
        for alias in model.get("aliases") or []:
            alias_owners.setdefault(str(alias).strip().lower(), set()).add(model["name"])

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
        seen_aliases: set[str] = set()
        for alias in model.get("aliases") or []:
            alias_key = str(alias).strip().lower()
            if alias_key in seen_aliases or len(alias_owners.get(alias_key, set())) != 1:
                continue
            seen_aliases.add(alias_key)
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
    auth = authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))

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
    auth = authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))
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


# ---------------------------------------------------------------------------
# OpenAI Batch API (files + batches)
#
# Registered ahead of the POST-only catch-alls, which cannot answer the GET and
# DELETE half of the lifecycle. Every operation is served by
# logos.batch_api.handle_batch_api_request: authenticate, authorise, forward to
# the provider's Batch API, account for the result.
# ---------------------------------------------------------------------------

_BATCH_API_ROUTES = (
    ("POST", "files"),
    ("GET", "files"),
    ("GET", "files/{file_id}"),
    ("GET", "files/{file_id}/content"),
    ("DELETE", "files/{file_id}"),
    ("POST", "batches"),
    ("GET", "batches"),
    ("GET", "batches/{batch_id}"),
    ("POST", "batches/{batch_id}/cancel"),
)


async def _batch_api_route(request: Request):
    """Serve one Batch API operation under any proxy prefix."""
    return await handle_batch_api_request(request)


for _batch_prefix in ("v1", "openai", "jobs/v1", "jobs/openai"):
    for _batch_method, _batch_path in _BATCH_API_ROUTES:
        router.add_api_route(
            f"/{_batch_prefix}/{_batch_path}",
            _batch_api_route,
            methods=[_batch_method],
            tags=["batch"],
            include_in_schema=_batch_prefix == "v1",
        )


@router.post("/v1/web-search", tags=["user-facing"])
async def web_search(body: WebSearchRequest, request: Request):
    """Return DuckDuckGo results through the existing API-key gateway."""
    authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))
    try:
        results = await search_web(body.query, body.max_results)
    except SearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"query": body.query, "source": "DuckDuckGo", "results": results}


_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    422: "invalid_request_error",
    429: "rate_limit_error",
    529: "overloaded_error",
}


async def _pipeline_turn(path: str, request: Request, payload: dict) -> tuple[int, Optional[dict]]:
    """One non-streaming request through the normal pipeline, in process.

    The client's own request with a different body: same headers, so the same
    key, client IP and routing hints; a fresh request id and log entry, so the
    turn is accounted like any other. The body stream ends after the payload
    and then waits instead of reporting a disconnect — a client that leaves
    cancels the task running this turn instead.

    Returns the status and the JSON body, ``None`` for an unreadable one.
    Raises the pipeline's HTTPException for a request it rejects.
    """
    raw = json.dumps(payload).encode()
    headers = [(k, v) for k, v in request.scope["headers"] if k.lower() != b"content-length"]
    headers.append((b"content-length", str(len(raw)).encode()))
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.Event().wait()

    turn = Request({**request.scope, "headers": headers}, receive)
    response = await handle_sync_request(path, turn)
    if isinstance(response, StreamingResponse):
        body = b"".join(
            [chunk if isinstance(chunk, bytes) else chunk.encode() async for chunk in response.body_iterator]
        )
    else:
        body = response.body
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return response.status_code, data


async def _messages_turn(request: Request, payload: dict) -> tuple[int, dict]:
    """One non-streaming Messages request through the normal pipeline, in process."""
    try:
        status, data = await _pipeline_turn("v1/messages", request, payload)
    except HTTPException as exc:
        status = exc.status_code
        return status, {
            "type": "error",
            "error": {"type": _ERROR_TYPES.get(status, "api_error"), "message": str(exc.detail)},
        }
    if data is None:
        return 502, {
            "type": "error",
            "error": {"type": "api_error", "message": "The model returned an unreadable response."},
        }
    if status != 200:
        return status, translate_error(data)
    return 200, data


async def _serve_server_web_search(request: Request, payload: dict, tool: dict):
    """Answer a Messages request that carries Anthropic's web search server tool."""
    # Rejected up front: a stream, once open, can only report it as an error
    # event, and a bad key deserves its 401.
    authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))

    async def turn(body: dict) -> tuple[int, dict]:
        return await _messages_turn(request, body)

    if not payload.get("stream"):
        status, body = await server_web_search.run(payload, tool, turn)
        return JSONResponse(body, status_code=status)

    async def events():
        message_id = f"msg_{secrets.token_hex(12)}"
        yield server_web_search.stream_start(message_id, payload.get("model"))
        work = asyncio.create_task(server_web_search.run(payload, tool, turn))
        try:
            # Model turns and searches add up to minutes on a cold model;
            # pings keep proxies and the client from timing the stream out.
            while True:
                done, _ = await asyncio.wait({work}, timeout=10)
                if done:
                    break
                yield server_web_search.stream_ping()
            try:
                status, message = work.result()
            except Exception:  # The stream is open: report it there, not as a cut-off.
                logger.exception("Web search for a Messages request failed")
                status, message = 500, {
                    "type": "error",
                    "error": {"type": "api_error", "message": "Web search failed."},
                }
        finally:
            work.cancel()
        if status != 200:
            yield server_web_search.stream_error(status, message)
            return
        for event in server_web_search.stream_rest({**message, "id": message_id}):
            yield event

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/v1/systemone", tags=["decisions"], summary="Answer typed questions with a decision model")
async def system_one(body: SystemOneRequest, request: Request):
    """Answer noul, choice and score questions about a state with calibrated probabilities.

    Each question is one completion on the decision model's lane, run through
    the normal pipeline (authorisation, scheduling, logging, billing).
    """
    authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))

    async def turn(path: str, payload: dict) -> tuple[int, Optional[dict]]:
        try:
            status, data = await _pipeline_turn(path, request, payload)
            if data is None:
                return 502, {"error": {"message": "The model returned an unreadable response."}}
            return status, data
        except HTTPException as exc:
            return exc.status_code, {"error": {"message": str(exc.detail)}}

    # Each turn's synthetic receive waits forever after the body, so the
    # pipeline's disconnect watcher cannot see the caller leave. Race the
    # decision work against a watcher on the ORIGINAL request and cancel when
    # the client goes away — otherwise up to 32 question completions keep
    # running after nobody is left to read them.
    work = asyncio.create_task(answer_system_one(body, turn))
    watcher = asyncio.create_task(_main._wait_for_client_disconnect(request))
    try:
        done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        await _main._settle(work)
        raise
    finally:
        await _main._settle(watcher)

    if work in done and watcher not in done:
        try:
            return work.result()
        except DecisionError as exc:
            if exc.body is not None:
                return JSONResponse(exc.body, status_code=exc.status)
            # Locally raised failures: invalid_request_error only for 400/422;
            # other statuses map through _ERROR_TYPES with api_error as fallback.
            return JSONResponse(
                {
                    "error": {
                        "message": str(exc),
                        "type": _ERROR_TYPES.get(exc.status, "api_error"),
                    }
                },
                status_code=exc.status,
            )

    await _main._settle(work)
    logger.info("Cancelled /v1/systemone: client disconnected before the response was ready")
    return JSONResponse(status_code=499, content={"detail": "Client closed request"})


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
    if path == "messages":
        raw = await request.body()
        if b'"web_search_' in raw:
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = None
            tool = server_web_search.server_web_search_tool(payload)
            if tool is not None:
                return await _serve_server_web_search(request, payload, tool)
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
# These are canonical paths for pooling, scoring, reranking, classification,
# and tokenization.
async def _handle_vllm_native(request: Request):
    """Forward to vLLM using the original request path."""
    path = request.url.path.lstrip("/")
    return await handle_sync_request(path, request)


for _vllm_path in ("/pooling", "/score", "/rerank", "/classify", "/tokenize", "/detokenize"):
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
    auth = authenticate_api_key(dict(request.headers), client_ip=get_client_ip(request))

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

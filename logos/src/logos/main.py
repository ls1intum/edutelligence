import asyncio
import datetime
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Set, Optional, Tuple
import grpc
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from logos.auth import authenticate_logos_key
from grpclocal import model_pb2_grpc
from grpclocal.grpc_server import LogosServicer
from logos.classification.classification_balancer import Balancer
from logos.classification.classification_manager import ClassificationManager
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.types import Deployment, get_unique_models_from_deployments
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.dbrequest import *
from logos.jobs.job_service import JobService, JobSubmission
from logos.responses import (
    get_client_ip,
    extract_model,
    request_setup,
    extract_token_usage
)
from logos.pipeline.pipeline import RequestPipeline, PipelineRequest
from logos.pipeline.fcfs_scheduler import FcfScheduler
from logos.pipeline.executor import Executor, ExecutionResult
from logos.pipeline.context_resolver import ContextResolver
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.monitoring.ollama_monitor import OllamaProviderMonitor
from scripts import setup_proxy

_SERVER_START_TIME = int(time.time())

logger = logging.getLogger("LogosLogger")
_grpc_server = None
_background_tasks: Set[asyncio.Task] = set()
_ollama_monitor: Optional[OllamaProviderMonitor] = None


def _record_azure_rate_limits(
    scheduling_stats: Optional[Dict[str, Any]],
    headers: Dict[str, str],
) -> None:
    if not scheduling_stats or not headers:
        return
    request_id = scheduling_stats.get("request_id")
    if not request_id:
        return

    headers_lower = {k.lower(): v for k, v in headers.items()}
    remaining_requests = headers_lower.get("x-ratelimit-remaining-requests")
    remaining_tokens = headers_lower.get("x-ratelimit-remaining-tokens")

    provider_metrics = {}
    if remaining_requests is not None:
        try:
            provider_metrics["azure_rate_remaining_requests"] = int(remaining_requests)
        except (TypeError, ValueError):
            pass
    if remaining_tokens is not None:
        try:
            provider_metrics["azure_rate_remaining_tokens"] = int(remaining_tokens)
        except (TypeError, ValueError):
            pass

    if provider_metrics:
        _pipeline.record_provider_metrics(request_id, provider_metrics)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown lifecycle.
    Initializes the request pipeline components and gRPC server.
    """

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )
    logging.getLogger("logos").setLevel(logging.INFO)
    logging.getLogger("logos.sdi.providers.ollama_provider").setLevel(logging.DEBUG)

    # Start Pipeline
    await start_pipeline()

    # Start Ollama provider monitoring
    global _ollama_monitor
    _ollama_monitor = OllamaProviderMonitor()
    await _ollama_monitor.start()
    logger.info("Ollama provider monitoring started")

    # Start gRPC server
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(_pipeline), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()

    yield

    # Shutdown logic
    # Stop Ollama provider monitoring
    if _ollama_monitor:
        await _ollama_monitor.stop()

    if _grpc_server:
        await _grpc_server.stop(0)


# Initialize FastAPI app with lifespan
app = FastAPI(docs_url="/docs", openapi_url="/openapi.json", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion ggf. einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # logos_key etc.
)


# Temporary CORS helper to unblock local testing; safe to remove when Traefik/CORS is stable.
@app.middleware("http")
async def add_star_cors_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        response = JSONResponse(content={}, status_code=200)
    else:
        response = await call_next(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _extract_policy(headers: dict, logos_key: str, body: dict):
    """
    Extract policy from request headers or model string.

    :param headers: Request headers dict
    :param logos_key: User's logos_key
    :param body: Request body (for model string parsing)
    :return: Policy dict or None (will default to ProxyPolicy)
    """
    from logos.model_string_parser import parse_model_string

    policy = None

    if "policy" in headers:
        try:
            policy_id = int(headers["policy"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="policy header must be an integer")
        try:
            with DBManager() as db:
                policy = db.get_policy(logos_key, policy_id)
                if isinstance(policy, dict) and "error" in policy:
                    raise HTTPException(
                        status_code=404,
                        detail="Policy not found for this process",
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Failed to load policy from header: {e}")
            raise HTTPException(status_code=500, detail="Failed to load policy")

    if policy is None:
        policy = {}

    try:
        mdl = extract_model(body)
        if mdl and mdl.startswith("logos-v"):
            model_string_dto = parse_model_string(mdl)
            p = model_string_dto.policy
            if not p.get("default"):
                for key in p:
                    if key == "default":
                        continue
                    if key == "privacy":
                        policy["threshold_privacy"] = p[key]
                    # Add other policy settings as needed
    except Exception as e:
        logger.debug(f"Could not parse model string for policy: {e}")

    return policy if policy else None


async def start_pipeline():
    """Initialize the new request pipeline components."""
    global _pipeline, _queue_mgr, _ollama_facade, _azure_facade, _context_resolver

    logger.info("Initializing Request Pipeline...")

    _queue_mgr = PriorityQueueManager()

    _ollama_facade = OllamaSchedulingDataFacade(_queue_mgr, None)
    _azure_facade = AzureSchedulingDataFacade(None)

    await _register_models_with_facades(_ollama_facade, _azure_facade)

    model_registry = _build_model_registry()
    scheduler = FcfScheduler(
        queue_manager=_queue_mgr,
        ollama_facade=_ollama_facade,
        azure_facade=_azure_facade,
        model_registry=model_registry
    )

    # 5. Executor
    executor = Executor()

    # 6. Context Resolver
    _context_resolver = ContextResolver()

    # 7. Classifier
    clf = classifier()

    # 8. Pipeline
    _pipeline = RequestPipeline(
        classifier=clf,
        scheduler=scheduler,
        executor=executor,
        context_resolver=_context_resolver
    )

    logger.info("Request Pipeline Initialized. with SDI-aware scheduling")


async def _register_models_with_facades(ollama_facade: OllamaSchedulingDataFacade, azure_facade: AzureSchedulingDataFacade):
    """Register all models with their respective SDI facades."""
    with DBManager() as db:
        deployments = db.get_all_deployments()
        if not deployments:
            logger.warning("No deployments found to register with SDI facades")
            return

        model_cache: Dict[int, Dict[str, Any]] = {}
        provider_cache: Dict[int, Dict[str, Any]] = {}

        for deployment in deployments:
            model_id = deployment["model_id"]
            provider_id = deployment["provider_id"]
            provider_type = (deployment.get("type") or "").lower()

            if model_id not in model_cache:
                model_info = db.get_model(model_id)
                if not model_info:
                    logger.warning("Model %s not found when registering providers", model_id)
                    continue
                model_cache[model_id] = model_info
            model_info = model_cache[model_id]
            model_name = model_info["name"]

            if provider_id not in provider_cache:
                provider_cache[provider_id] = db.get_provider(provider_id) or {}
            provider_info = provider_cache[provider_id]
            provider_name = provider_info.get("name", f"provider-{provider_id}")

            # Provider-level SDI config (VRAM, admin URL, etc.)
            provider_config = db.get_provider_config(provider_id) or {}

            if not provider_type:
                logger.warning(
                    "Skipping provider %s (%s) for model %s: missing provider_type",
                    provider_id,
                    provider_name,
                    model_id,
                )
                continue

            provider_type = provider_type.lower()

            if provider_type == "ollama":
                _ollama_facade.register_model(
                    model_id=model_id,
                    provider_name=provider_name,
                    ollama_admin_url=provider_config.get("ollama_admin_url"),
                    model_name=model_name,
                    total_vram_mb=provider_config.get("total_vram_mb", 65536),
                    provider_id=provider_id,
                )
            elif provider_type == "azure":
                endpoint = db.get_endpoint_for_deployment(model_id, provider_id)
                _azure_facade.register_model(
                    model_id=model_id,
                    provider_name=provider_name,
                    model_name=model_name,
                    model_endpoint=endpoint or "",
                    provider_id=provider_id,
                )
            else:
                logger.debug(
                    "Skipping provider %s (%s) for model %s: unsupported type '%s'",
                    provider_id,
                    provider_name,
                    model_id,
                    provider_type,
                )


def _build_model_registry() -> Dict[tuple[int, int], str]:
    """Build mapping of (model_id, provider_id) -> provider_type."""
    registry: Dict[tuple[int, int], str] = {}
    with DBManager() as db:
        for deployment in db.get_all_deployments():
            model_id = deployment["model_id"]
            provider_id = deployment["provider_id"]
            provider_type = deployment.get("type")
            if provider_type:
                registry[(model_id, provider_id)] = provider_type
    return registry


def classifier() -> ClassificationManager:
    """Build classifier with all models from database."""
    mdls = []
    with DBManager() as db:
        for model_id in db.get_all_models():
            tpl = db.get_model(model_id)
            if tpl:
                mdls.append({
                    "id": tpl["id"],
                    "name": tpl["name"],
                    "weight_privacy": tpl["weight_privacy"],
                    "weight_latency": tpl["weight_latency"],
                    "weight_accuracy": tpl["weight_accuracy"],
                    "weight_cost": tpl["weight_cost"],
                    "weight_quality": tpl["weight_quality"],
                    "tags": tpl["tags"],
                    "parallel": tpl["parallel"],
                    "description": tpl["description"],
                    "classification_weight": Balancer(),
                })

    return ClassificationManager(mdls)


def rebuild_classifier():
    """
    Rebuild classifier with current models from database.
    Updates the global pipeline's classifier instance.
    Called when models are added, updated, or deleted.
    """
    global _pipeline
    if _pipeline:
        new_classifier = classifier()
        _pipeline.update_classifier(new_classifier)
        logger.info("Classifier rebuilt with updated models")


def _streaming_response(context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats=None):
    """Build streaming response using executor."""
    from fastapi.responses import StreamingResponse

    async def streamer():
        full_text = ""
        first_chunk = None
        last_chunk = None
        error_message = None
        timed_out = False
        ttft_recorded = False

        try:
            def process_headers(headers: dict):
                try:
                    _pipeline.update_provider_stats(model_id, provider_id, headers)
                except Exception:
                    pass
                try:
                    _record_azure_rate_limits(scheduling_stats, headers)
                except Exception:
                    pass

            # Prepare headers and payload using context resolver
            headers, prepared_payload = _context_resolver.prepare_headers_and_payload(context, payload)

            async for chunk in _pipeline.executor.execute_streaming(
                context.forward_url,
                headers,
                prepared_payload,
                on_headers=process_headers,
            ):
                yield chunk
                if chunk and not ttft_recorded:
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)
                    ttft_recorded = True

                # Parse chunk for logging
                line = chunk.decode().strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        blob = json.loads(line[6:])
                        last_chunk = blob  # Keep track of last chunk (may have usage)
                        if first_chunk is None:
                            first_chunk = blob
                        if "choices" in blob and blob["choices"]:
                            delta = blob["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_text += content
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            error_message = str(e)
            raise e
        finally:
            # Log completion with detailed token usage
            if log_id:
                # Extract usage from last chunk (OpenAI includes it with stream_options)
                usage = last_chunk.get("usage", {}) if last_chunk else {}
                usage_tokens = extract_token_usage(usage) if usage else {}

                # Build response payload
                response_payload = {"content": full_text}
                base_payload = None
                if first_chunk:
                    base_payload = first_chunk.copy()
                if last_chunk:
                    if base_payload is None:
                        base_payload = last_chunk.copy()
                    else:
                        for key, value in last_chunk.items():
                            if key not in base_payload:
                                base_payload[key] = value
                if base_payload:
                    response_payload = base_payload
                    if "choices" in response_payload and response_payload["choices"]:
                        response_payload["choices"][0]["delta"] = {"content": full_text}
                if usage:
                    response_payload["usage"] = usage

                with DBManager() as db:
                    db.set_response_payload(
                        log_id,
                        response_payload,
                        provider_id,
                        model_id,
                        usage_tokens,
                        policy_id,
                        classification_stats,
                        request_id=scheduling_stats.get("request_id") if scheduling_stats else None,
                        queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None,
                        utilization_at_arrival=scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                    )

            if scheduling_stats:
                status = "timeout" if timed_out else ("error" if error_message else "success")
                
                _pipeline.record_completion(
                    request_id=scheduling_stats.get("request_id"),
                    result_status=status,
                    error_message=error_message,
                    cold_start=scheduling_stats.get("is_cold_start")
                )
            
            # Release scheduler resources
            if scheduling_stats and scheduling_stats.get("request_id"):
                try:
                    _pipeline.scheduler.release(
                        model_id,
                        provider_id,
                        scheduling_stats.get("provider_type"),
                        scheduling_stats.get("request_id")
                    )
                except Exception as e:
                    logger.error(f"Failed to release scheduler resources: {e}")
    
    return StreamingResponse(streamer(), media_type="text/event-stream")


async def _sync_response(context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats=None, is_async_job=False):
    """Execute sync request and return response."""
    from fastapi.responses import JSONResponse

    try:
        # Prepare headers and payload using context resolver
        headers, prepared_payload = _context_resolver.prepare_headers_and_payload(context, payload)

        timed_out = False
        error_message = None

        exec_result = await _pipeline.executor.execute_sync(context.forward_url, headers, prepared_payload)

        # Update rate limits from response headers
        if exec_result.headers:
            try:
                _pipeline.update_provider_stats(model_id, provider_id, exec_result.headers)
            except Exception:
                pass
            try:
                _record_azure_rate_limits(scheduling_stats, exec_result.headers)
            except Exception:
                pass

        response_payload = exec_result.response
        if not exec_result.success:
            if not response_payload and exec_result.error:
                response_payload = {"error": exec_result.error}
            logger.error(
                f"Request failed (model_id={model_id}, provider_id={provider_id}): "
                f"{exec_result.error}, response={response_payload}"
            )

        if log_id:
            # Extract detailed token usage
            usage = response_payload.get("usage", {}) if response_payload else {}
            usage_tokens = extract_token_usage(usage) if usage else {}

            with DBManager() as db:
                db.set_time_at_first_token(log_id)
                db.set_response_timestamp(log_id)
                db.set_response_payload(
                    log_id,
                    response_payload,
                    provider_id,
                    model_id,
                    usage_tokens,
                    policy_id,
                    classification_stats,
                    request_id=scheduling_stats.get("request_id") if scheduling_stats else None,
                    queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None,
                    utilization_at_arrival=scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                )

        if scheduling_stats:
            status = "timeout" if timed_out else ("success" if exec_result.success else "error")
            _pipeline.record_completion(
                request_id=scheduling_stats.get("request_id"),
                result_status=status,
                error_message=error_message if timed_out else (exec_result.error if not exec_result.success else None),
                cold_start=scheduling_stats.get("is_cold_start")
            )

        # Return dict for async jobs, JSONResponse for sync endpoints
        if is_async_job:
            status_code = 504 if timed_out else (200 if exec_result.success else 500)
            return {"status_code": status_code, "data": response_payload}
        else:
            status_code = 504 if timed_out else (200 if exec_result.success else 500)
            return JSONResponse(content=exec_result.response, status_code=status_code)

    finally:
        if scheduling_stats and scheduling_stats.get("request_id"):
            try:
                _pipeline.scheduler.release(
                    model_id,
                    provider_id,
                    scheduling_stats.get("provider_type"),
                    scheduling_stats.get("request_id")
                )
            except Exception as e:
                logger.error(f"Failed to release scheduler resources: {e}")


def _proxy_streaming_response(forward_url: str, proxy_headers: dict, payload: dict,
                               log_id: Optional[int], provider_id: int, model_id: Optional[int],
                               policy_id: int, classified: dict):
    """
    Build streaming response for PROXY MODE using executor.
    """
    from fastapi.responses import StreamingResponse
    import datetime

    async def streamer():
        full_text = ""
        first_chunk = None
        last_chunk = None
        ttft = None

        try:
            async for chunk in _pipeline.executor.execute_streaming(
                forward_url, proxy_headers, payload
            ):
                # Track time to first token
                if ttft is None:
                    ttft = datetime.datetime.now(datetime.timezone.utc)
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)

                yield chunk

                # Parse chunk for logging
                line = chunk.decode().strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        blob = json.loads(line[6:])
                        last_chunk = blob
                        if first_chunk is None:
                            first_chunk = blob
                        if "choices" in blob and blob["choices"]:
                            delta = blob["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_text += content
                    except json.JSONDecodeError:
                        pass
        finally:
            # Log completion
            if log_id:
                usage = last_chunk.get("usage", {}) if last_chunk else {}
                usage_tokens = extract_token_usage(usage) if usage else {}

                response_payload = {"content": full_text}
                base_payload = None
                if first_chunk:
                    base_payload = first_chunk.copy()
                if last_chunk:
                    if base_payload is None:
                        base_payload = last_chunk.copy()
                    else:
                        for key, value in last_chunk.items():
                            if key not in base_payload:
                                base_payload[key] = value
                if base_payload:
                    response_payload = base_payload
                    if "choices" in response_payload and response_payload["choices"]:
                        response_payload["choices"][0]["delta"] = {"content": full_text}
                if usage:
                    response_payload["usage"] = usage

                with DBManager() as db:
                    if ttft is None:
                        db.set_time_at_first_token(log_id)
                    db.set_response_payload(
                        log_id, response_payload, provider_id, model_id,
                        usage_tokens, policy_id, classified
                    )

    return StreamingResponse(streamer(), media_type="text/event-stream")


async def _proxy_sync_response(forward_url: str, proxy_headers: dict, payload: dict,
                                log_id: Optional[int], provider_id: int, model_id: Optional[int],
                                policy_id: int, classified: dict, is_async_job=False):
    """
    Build synchronous response for PROXY MODE using executor.
    """
    from fastapi.responses import JSONResponse

    exec_result = await _pipeline.executor.execute_sync(
        forward_url, proxy_headers, payload
    )

    response_payload = exec_result.response
    if not exec_result.success and not response_payload and exec_result.error:
        response_payload = {"error": exec_result.error}

    if log_id:
        usage_tokens = extract_token_usage(exec_result.usage) if exec_result.usage else {}

        with DBManager() as db:
            db.set_time_at_first_token(log_id)
            db.set_response_timestamp(log_id)
            db.set_response_payload(
                log_id, response_payload, provider_id, model_id,
                usage_tokens, policy_id, classified
            )

    # Return dict for async jobs, JSONResponse for sync endpoints
    if is_async_job:
        return {"status_code": 200 if exec_result.success else 500, "data": response_payload}
    else:
        return JSONResponse(content=response_payload, status_code=200 if exec_result.success else 500)


async def _execute_proxy_mode(
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    deployments: list[Deployment],
    log_id: Optional[int],
    is_async_job: bool,
    profile_id: Optional[int] = None
):
    """
    Direct model execution: skip classification, reuse scheduling/SDI, resolve auth from DB.

    Resolves the requested model from the DB (access-controlled by logos_key), then reuses the
    resource-mode pipeline with allowed_models restricted to that model.
    """
    model_name = body.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="Proxy mode requires 'model' in payload")

    with DBManager() as db:
        models_info = db.get_models_info(logos_key)

    model_id = None
    for row in models_info:
        mid, name = row[0], row[1]
        if name == model_name:
            model_id = mid
            break

    if model_id is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not available for this key")

    # Ensure payload model matches DB name (avoid user-supplied mismatch)
    body = {**body, "model": model_name}

    # Narrow deployments to the requested model to preserve provider metadata
    model_deployments = [d for d in deployments if d["model_id"] == model_id]
    if not model_deployments:
        raise HTTPException(status_code=404, detail=f"No deployment found for model '{model_name}'")

    # Proxy mode reuses the execution from RESOURCE mode with single allowed model -> effectively skipping the classification
    return await _execute_resource_mode(
        deployments=model_deployments,
        body=body,
        headers=headers,
        logos_key=logos_key,
        log_id=log_id,
        is_async_job=is_async_job,
        allowed_models_override=[model_id],
        profile_id=profile_id
    )


async def _execute_resource_mode(
    deployments: list[Deployment],
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    log_id: Optional[int],
    is_async_job: bool,
    allowed_models_override: Optional[list] = None,
    profile_id: Optional[int] = None
):
    """
    Execute request in RESOURCE mode (classification + scheduling).

    RESOURCE mode uses the full request processing pipeline:
    1. **Classification** - Selects best model from available models using ML classifier
    2. **Scheduling** - Queues request considering model utilization and cold starts
    3. **Execution** - Makes API call to the selected model

    This mode is used when body["model"] is NOT specified, allowing the system to
    automatically choose the optimal model based on request characteristics and
    current system state.

    The scheduler is aware of:
    - Real-time model availability (via Ollama/Azure SDI facades)
    - Current queue depths per model
    - Cold start penalties
    - Model utilization levels

    Args:
        deployments: List of available deployments(model_id, provider_id) from request_setup()
        body: Request payload (should NOT contain "model" field)
        headers: Request headers
        logos_key: User's logos authentication key
        log_id: Usage log ID for tracking (None for requests without logging)
        is_async_job: Whether this is a background job (affects error handling)
            - False: Direct endpoint - raises HTTPException for errors
            - True: Background job - returns error dict for errors

    Returns:
        - For direct endpoints (is_async_job=False):
            - StreamingResponse if body["stream"] is True
            - JSONResponse if body["stream"] is False
        - For background jobs (is_async_job=True):
            - Dict with {"status_code": int, "data": response_payload}

    Raises:
        HTTPException: Only when is_async_job=False and an error occurs
    """
    allowed_models = get_unique_models_from_deployments(deployments)
    # Extract policy
    policy = _extract_policy(headers, logos_key, body)

    # Create Pipeline Request
    pipeline_req = PipelineRequest(
        logos_key=logos_key or "anon",
        payload=body,
        headers=headers,
        policy=policy,
        allowed_models=allowed_models,
        deployments=deployments,
        profile_id=profile_id
    )

    # Process through classification and scheduling
    result = await _pipeline.process(pipeline_req)

    if not result.success:
        error_msg = result.error or "Pipeline processing failed"
        if is_async_job:
            return {"status_code": 503, "data": {"error": error_msg}}
        else:
            raise HTTPException(status_code=503, detail=error_msg)

    # Execute and Respond
    try:
        if is_async_job:
            # Async jobs are always non-streaming - use helper
            return await _sync_response(
                result.execution_context,
                body,
                log_id,
                result.provider_id,
                result.model_id,
                -1,  # policy_id
                result.classification_stats,
                result.scheduling_stats,
                is_async_job=True
            )
        else:
            # Sync endpoints support streaming
            if body.get("stream"):
                return _streaming_response(
                    result.execution_context,
                    body,
                    log_id,
                    result.provider_id,
                    result.model_id,
                    -1,  # Policy ID not implemented
                    result.classification_stats,
                    result.scheduling_stats
                )
            else:
                return await _sync_response(
                    result.execution_context,
                    body,
                    log_id,
                    result.provider_id,
                    result.model_id,
                    -1,  # Policy ID not implemented
                    result.classification_stats,
                    result.scheduling_stats
                )
    except Exception as e:
        logger.error(f"Error in _execute_resource_mode: {e}", exc_info=True)
        try:
            _pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status="error",
                error_message=str(e)
            )
        except Exception as record_err:
            logger.error(f"Failed to record completion: {record_err}")

        if is_async_job:
            return {"status_code": 500, "data": {"error": str(e)}}
        else:
            raise e


async def route_and_execute(
    deployments: list[dict[str, int]],
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    path: str,
    log_id: Optional[int],
    is_async_job: bool = False,
    profile_id: Optional[int] = None
):
    """
    Route request to PROXY or RESOURCE mode and execute.

    This is the main entry point for all request handling. It decides between two execution modes:

    **PROXY MODE** (when body["model"] is specified):
    - Bypasses classification/scheduling pipeline
    - Forwards directly to the specified provider
    - User has full control over model/provider selection

    **RESOURCE MODE** (when body["model"] is NOT specified):
    - Full pipeline: Classification → Scheduling → Execution
    - System automatically selects optimal model
    - Scheduler considers utilization, queue depth, and cold starts

    Routing logic:
    - Case 1: No deployments available → 404 error
    - Case 2: body["model"] specified → PROXY mode (direct forwarding)
    - Case 3: no body["model"] → RESOURCE mode (classification + scheduling)

    Args:
        deployments: List of available deployments(model_id, provider_id) from request_setup()
        body: Request payload
        headers: Request headers
        logos_key: User's logos authentication key
        path: API endpoint path (e.g., "chat/completions")
        log_id: Usage log ID for tracking (None for requests without logging)
        is_async_job: Whether this is a background job (affects error handling)
            - False: Direct endpoint - client waits, raises HTTPException for errors
            - True: Background job - client gets job_id, returns error dict for errors
        profile_id: Profile ID for authorization (enforces profile-based model access)

    Returns:
        - For direct endpoints (is_async_job=False):
            - StreamingResponse if body["stream"] is True
            - JSONResponse if body["stream"] is False
        - For background jobs (is_async_job=True):
            - Dict with {"status_code": int, "data": response_payload}

    Raises:
        HTTPException: Only when is_async_job=False and an error occurs

    See Also:
        _execute_proxy_mode(): PROXY mode implementation
        _execute_resource_mode(): RESOURCE mode implementation
    """
    # No models available → ERROR
    if not deployments:
        if is_async_job:
            return {"status_code": 404, "data": {"error": "No models available for this user."}}
        else:
            raise HTTPException(
                status_code=404,
                detail="No models available for this user."
            )

    try:
        # PROXY mode (body["model"] specified → direct forwarding)
        if body.get("model"):
            return await _execute_proxy_mode(body, headers, logos_key, deployments, log_id, is_async_job, profile_id=profile_id)

        # RESOURCE mode (no body["model"] → classification + scheduling)
        return await _execute_resource_mode(deployments, body, headers, logos_key, log_id, is_async_job, profile_id=profile_id)
    except HTTPException as exc:
        if is_async_job:
            return {"status_code": exc.status_code, "data": {"error": exc.detail}}
        raise


async def handle_sync_request(path: str, request: Request):
    """
    Handle synchronous (non-job) requests for both /v1 and /openai endpoints.

    Performs authentication, model setup, and routing/execution.

    Args:
        path: API endpoint path
        request: FastAPI request object

    Returns:
        Response (StreamingResponse or JSONResponse)
    """
    # Authenticate with profile-based auth (REQUIRED for v1/openai/jobs endpoints)
    headers, auth, body, client_ip, log_id = await auth_parse_log(request, use_profile_auth=True)

    # Get available deployments (model, provider tuple) for THIS profile - profile_id EXPLICITLY passed
    try:
        deployments = request_setup(headers, auth.logos_key, profile_id=auth.profile_id)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not deployments:
        raise HTTPException(status_code=404, detail="No available model deployments for this profile")

    # Route and execute request with profile context
    return await route_and_execute(
        deployments, body, headers, auth.logos_key, path, log_id,
        profile_id=auth.profile_id
    )


async def auth_parse_log(request: Request, use_profile_auth: bool = False):
    """
    Authenticate, parse, and log incoming requests.

    This helper centralizes auth, body parsing, and logging for all endpoints.
    Used by /openai, /v1, and /jobs/* endpoints.

    Args:
        request: FastAPI request object
        use_profile_auth: If True, use profile-based auth and return AuthContext

    Returns:
        If use_profile_auth=False (default):
            (headers, logos_key, process_id, body, client_ip, log_id)
        If use_profile_auth=True:
            (headers, auth_context, body, client_ip, log_id)

    Raises:
        HTTPException(400): Invalid JSON body
        HTTPException(401): Missing or invalid authentication
    """
    # Parse body
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    # Extract headers and client IP
    headers = dict(request.headers)
    client_ip = get_client_ip(request)

    # Authenticate
    if use_profile_auth:
        from logos.auth import authenticate_with_profile
        auth = authenticate_with_profile(headers)
        process_id = auth.process_id

        # Log request (still at process level for billing)
        log_id = None
        with DBManager() as db:
            r_log, c_log = db.log_usage(process_id, client_ip, body, headers)
            if c_log == 200:
                log_id = int(r_log["log-id"])

        return headers, auth, body, client_ip, log_id
    else:
        # For endpoints not requiring the profile-based authorization
        logos_key, process_id = authenticate_logos_key(headers)

        # Log request
        log_id = None
        with DBManager() as db:
            r_log, c_log = db.log_usage(process_id, client_ip, body, headers)
            if c_log == 200:
                log_id = int(r_log["log-id"])

        return headers, logos_key, process_id, body, client_ip, log_id


async def submit_job_request(path: str, request: Request) -> JSONResponse:
    """
    Accept a proxy request, persist it as a job, and launch async processing (poll for result via /jobs/{id}).

    Params:
        path: Upstream path to forward.
        request: Incoming FastAPI request containing headers/body.

    Returns:
        202 Accepted with job id and status URL.

    Raises:
        HTTPException(400/401) on invalid payload or auth.
    """
    # Auth with profile + logging
    headers, auth, json_data, client_ip, log_id = await auth_parse_log(request, use_profile_auth=True)

    # Persist job and run it asynchronously
    job_payload = JobSubmission(
        path=path,
        method=request.method,
        headers=headers,
        body=json_data,
        client_ip=client_ip,
        process_id=auth.process_id,
        profile_id=auth.profile_id,
    )
    job_id = JobService.create_job(job_payload)
    status_url = str(request.url_for("get_job_status", job_id=job_id))

    # Fire-and-forget: run the heavy proxy/classification pipeline off the request path.
    task = asyncio.create_task(process_job(job_id, path, headers, dict(json_data), client_ip, auth))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(status_code=202, content={"job_id": job_id, "status_url": status_url, "profile_id": auth.profile_id})


async def process_job(job_id: int, path: str, headers: Dict[str, str], json_data: Dict[str, Any], client_ip: str, auth):
    """
    Execute a job and persist success or failure.

    Args:
        job_id: Job ID
        path: API path
        headers: Request headers
        json_data: Request body
        client_ip: Client IP address
        auth: AuthContext with profile information
    """
    try:
        JobService.mark_running(job_id)
        result = await execute_proxy_job(path, headers, json_data, client_ip, auth)
        JobService.mark_success(job_id, result)
    # Exception while processing the job is caught and persisted in the database
    except Exception as e:
        logging.exception("Job %s failed", job_id)
        JobService.mark_failed(job_id, str(e))
        return {"status_code": 500, "data": {"error": "Job failed"}}
    return result


async def execute_proxy_job(path: str, headers: Dict[str, str], json_data: Dict[str, Any], client_ip: str, auth) -> Dict[str, Any]:
    """
    Execute the proxy workflow using either PROXY MODE or RESOURCE MODE pipeline.
    Force non-streaming for async job execution.

    Args:
        path: API path
        headers: Request headers
        json_data: Request body
        client_ip: Client IP
        auth: AuthContext with profile information

    Returns:
        Serializable dict result with status_code and data.
    """
    headers = headers or dict()
    json_data = json_data or dict()

    # Log usage (at process level for billing)
    usage_id = None
    with DBManager() as db:
        r, c = db.log_usage(auth.process_id, client_ip, json_data, headers)
        if c != 200:
            logging.info("Error while logging a request: %s", r)
        else:
            usage_id = int(r["log-id"])

    # Get available models for this profile - profile_id EXPLICITLY passed
    try:
        models = request_setup(headers, auth.logos_key, profile_id=auth.profile_id)
    except PermissionError as e:
        return {"status_code": 401, "data": {"error": str(e)}}
    except ValueError as e:
        return {"status_code": 400, "data": {"error": str(e)}}

    # Force non-streaming for jobs
    json_data["stream"] = False

    # Route and execute request (async job mode) with profile context
    return await route_and_execute(
        models, json_data, headers, auth.logos_key, path, usage_id,
        is_async_job=True,
        profile_id=auth.profile_id
    )


# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/logosdb/setup")
async def setup_db(data: LogosSetupRequest):
    try:
        logging.info("Receiving setup request...")
        with DBManager() as db:
            db.is_root_initialized()
        logging.info("Processing setup request. Initialized: %s", str(DBManager.is_initialized()))
        if not DBManager.is_initialized():
            # First-time setup: create initial provider and process
            lk = setup_proxy.setup(**data.dict())
            if "error" in lk:
                return lk, 500
            return {"logos-key": lk}
        return {"error": "Database already initialized"}, 500
    except Exception as e:
        return {"error": f"{str(e)}"}, 500


@app.post("/logosdb/add_service_proxy")
async def add_service_proxy(data: AddServiceProxyRequest):
    try:
        with DBManager() as db:
            db.is_root_initialized()
        if not DBManager.is_initialized():
            return {"error": "Database not initialized"}, 500
        lk = setup_proxy.add_service(**data.dict())
        if "error" in lk:
            return lk, 500
        return {"service-key": lk,}, 200
    except Exception as e:
        return {"error": f"{str(e)}"}, 500


@app.post("/logosdb/set_log")
async def set_log(data: SetLogRequest):
    with DBManager() as db:
        check, code = db.get_process_id(data.dict()["logos_key"])
        if "error" in check:
            return check, code
        if check["result"] != data.dict()["process_id"] and not db.check_authorization(data.dict()["logos_key"]):
            return {"error": "Missing authentication to set log"}
        return db.set_process_log(data.dict()["process_id"], data.dict()["set_log"])


@app.post("/logosdb/add_provider")
async def add_provider(data: AddProviderRequest):
    with DBManager() as db:
        return db.add_provider(**data.dict())


@app.post("/logosdb/add_profile")
async def add_profile(data: AddProfileRequest):
    with DBManager() as db:
        return db.add_profile(**data.dict())


@app.post("/logosdb/connect_process_provider")
async def connect_process_provider(data: ConnectProcessProviderRequest):
    with DBManager() as db:
        return db.connect_process_provider(**data.dict())


@app.post("/logosdb/connect_process_model")
async def connect_process_model(data: ConnectProcessModelRequest):
    with DBManager() as db:
        return db.connect_process_model(**data.dict())


@app.post("/logosdb/connect_profile_model")
async def connect_profile_model(data: ConnectProcessModelRequest):
    with DBManager() as db:
        return db.connect_profile_model(**data.dict())


@app.post("/logosdb/connect_service_process")
async def connect_service_process(data: ConnectServiceProcessRequest):
    with DBManager() as db:
        return db.connect_service_process(**data.dict())


@app.post("/logosdb/connect_model_provider")
async def connect_model_provider(data: ConnectModelProviderRequest):
    with DBManager() as db:
        return db.connect_model_provider(**data.dict())


@app.post("/logosdb/connect_model_api")
async def connect_model_api(data: ConnectModelApiRequest):
    with DBManager() as db:
        return db.connect_model_api(**data.dict())


@app.post("/logosdb/add_model")
async def add_model(data: AddModelRequest):
    with DBManager() as db:
        back = db.add_model(**data.dict())
    rebuild_classifier()
    return back


@app.post("/logosdb/add_full_model")
async def add_full_model(data: AddFullModelRequest):
    with DBManager() as db:
        back = db.add_full_model(**data.dict())
    rebuild_classifier()
    return back


@app.post("/logosdb/update_model")
async def update_model(data: GiveFeedbackRequest):
    with DBManager() as db:
        back = db.update_model_weights(**data.dict())
    rebuild_classifier()
    return back


@app.post("/logosdb/delete_model")
async def delete_model(data: DeleteModelRequest):
    with DBManager() as db:
        back = db.delete_model(**data.dict())
    rebuild_classifier()
    return back


@app.post("/logosdb/get_model")
async def get_model(data: GetModelRequest):
    with DBManager() as db:
        return db.get_model(**data.dict()), 200


@app.post("/logosdb/add_policy")
async def add_policy(data: AddPolicyRequest):
    with DBManager() as db:
        return db.add_policy(**data.dict())


@app.post("/logosdb/update_policy")
async def update_policy(data: UpdatePolicyRequest):
    with DBManager() as db:
        return db.update_policy(**data.dict())


@app.post("/logosdb/delete_policy")
async def delete_policy(data: DeletePolicyRequest):
    with DBManager() as db:
        return db.delete_policy(**data.dict())


@app.post("/logosdb/get_policy")
async def add_model(data: GetPolicyRequest):
    with DBManager() as db:
        return db.get_policy(**data.dict()), 200


@app.post("/logosdb/add_service")
async def add_service(data: AddServiceRequest):
    with DBManager() as db:
        return db.add_service(**data.dict())


@app.post("/logosdb/get_process_id")
async def get_process_id(data: GetProcessIdRequest):
    with DBManager() as db:
        return db.get_process_id(data.logos_key)


@app.post("/logosdb/get_role")
async def get_role(data: GetRole):
    with DBManager() as db:
        return db.get_role(**data.dict())


@app.post("/logosdb/get_providers")
async def get_providers(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_provider_info(**data.dict()), 200


@app.post("/logosdb/get_general_provider_stats")
async def get_general_provider_stats(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_general_provider_stats(**data.dict())


@app.post("/logosdb/get_models")
async def get_models(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_models_info(**data.dict()), 200


@app.post("/logosdb/get_policies")
async def get_models(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_policy_info(**data.dict()), 200


@app.post("/logosdb/get_general_model_stats")
async def get_general_model_stats(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_general_model_stats(**data.dict())


@app.post("/logosdb/export")
async def export(data: LogosKeyModel):
    with DBManager() as db:
        return db.export(**data.dict())


@app.post("/logosdb/import")
async def import_json(data: GetImportDataRequest):
    with DBManager() as db:
        return db.import_from_json(**data.dict())


@app.get("/forward_host")
def route_handler(request: Request):
    host = request.headers.get("x-forwarded-host") or request.headers.get("forwarded")
    return {"host": host}


@app.post("/logosdb/add_billing")
async def add_billing(data: AddBillingRequest):
    with DBManager() as db:
        return db.add_billing(**data.dict())


@app.post("/logosdb/generalstats")
async def generalstats(data: LogosKeyModel):
    with DBManager() as db:
        return db.generalstats(**data.dict())


@app.post("/logosdb/request_event_stats")
async def request_event_stats(request: Request):
    """
    Aggregate request_events metrics for dashboards.

    Args:
        request: FastAPI request; must include authentication headers.
        Body supports:
            - start_date / end_date: ISO strings for the time window (defaults to last 30 days)
            - target_buckets: hint for how granular the time-series should be
            - include_raw_rows: optional raw rows for debugging (capped)

    Auth:
        - `logos_key` header (preferred), or
        - `Authorization: Bearer <logos_key>`

    Returns:
        Tuple[dict, int]: (payload, status) from DBManager.get_request_event_stats.
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    start_date = body.get("start_date")
    end_date = body.get("end_date")
    target_buckets = body.get("target_buckets", 120)

    with DBManager() as db:
        payload, status = db.get_request_event_stats(
            logos_key,
            start_date=start_date,
            end_date=end_date,
            target_buckets=target_buckets,
        )
        return JSONResponse(
            content=payload,
            status_code=status,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
            },
        )


@app.options("/logosdb/request_event_stats")
async def request_event_stats_options():
    """
    Local testing helper to dodge CORS preflight failures.
    Safe to remove once Traefik/CORS is sorted.
    """
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
    )


@app.get("/logosdb/scheduler_state")
async def scheduler_state(request: Request):
    """
    Debug endpoint to inspect in-memory scheduler and Ollama capacity state.
    """
    headers = dict(request.headers)
    authenticate_logos_key(headers)

    if not _pipeline or not _ollama_facade:
        return JSONResponse(content={"error": "Scheduler not initialized"}, status_code=503)

    payload = {
        "queue_total": _pipeline.scheduler.get_total_queue_depth(),
        "ollama": _ollama_facade.debug_state(),
    }
    return JSONResponse(content=payload, status_code=200)


@app.post("/logosdb/get_ollama_vram_stats")
async def get_ollama_vram_stats(request: Request):
    """
    Return time-series VRAM usage from ollama_provider_snapshots table.

    Request body:
    {
        "day": "2025-01-05",                    # Required: fetch a single UTC day
        "bucket_seconds": 5                     # Optional (ignored): kept for compatibility
    }

    Response:
    {
        "providers": [
            {
                "url": "http://host.docker.internal:11435",
                "data": [
                    {"timestamp": "2025-01-05T10:00:00Z", "vram_mb": 4608},
                    ...
                ]
            }
        ]
    }
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    # Parse request body for date filters (tolerate empty/no-body requests)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    day = body.get("day")
    if not day:
        return JSONResponse(content={"error": "Parameter 'day' is required (YYYY-MM-DD)."}, status_code=400)
    bucket_seconds = body.get("bucket_seconds", 5)  # Default 5s buckets to match UI expectation

    with DBManager() as db:
        payload, status = db.get_ollama_vram_stats(
            logos_key,
            day=day,
            bucket_seconds=bucket_seconds,
        )
        return JSONResponse(content=payload, status_code=status)


@app.options("/logosdb/get_ollama_vram_stats")
async def get_ollama_vram_stats_options():
    """CORS preflight for get_ollama_vram_stats."""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, logos_key",
        }
    )


# ============================================================================
# OPENAI-COMPATIBLE MODEL LISTING
# ============================================================================

@app.get("/v1/models")
async def list_models(request: Request):
    """
    List models accessible to the authenticated user (OpenAI-compatible).

    Returns an OpenAI-compatible response listing all models the user's
    current profile has access to via profile_model_permissions.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models spec.
    """
    from logos.auth import authenticate_with_profile
    auth = authenticate_with_profile(dict(request.headers))

    with DBManager() as db:
        models = db.get_models_for_profile(auth.profile_id)

    data = [
        {
            "id": model["name"],
            "object": "model",
            "created": _SERVER_START_TIME,
            "owned_by": "logos",
        }
        for model in models
    ]

    return JSONResponse(content={"object": "list", "data": data})


@app.get("/v1/models/{model_id:path}")
async def retrieve_model(model_id: str, request: Request):
    """
    Retrieve a single model by name (OpenAI-compatible).

    Verifies the authenticated user has access to the requested model
    through their profile's model permissions.

    Params:
        model_id: The model name (used as the OpenAI-style model id).
        request: Incoming request.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models/{model} spec.

    Raises:
        HTTPException(404): Model not found or user lacks access.
    """
    from logos.auth import authenticate_with_profile
    auth = authenticate_with_profile(dict(request.headers))

    with DBManager() as db:
        model = db.get_model_for_profile(auth.profile_id, model_id)

    if not model:
        raise HTTPException(status_code=404, detail="Model not found or access denied")

    return JSONResponse(content={
        "id": model["name"],
        "object": "model",
        "created": _SERVER_START_TIME,
        "owned_by": "logos",
    })


# ============================================================================
# MAIN API ENDPOINTS
# ============================================================================

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def logos_service_sync(path: str, request: Request):
    """
    Dynamic proxy for AI endpoints (versioned paths).
    Supports both PROXY and RESOURCE modes with streaming.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        Upstream response (streaming or sync) based on request.
    """
    return await handle_sync_request(path, request)


@app.api_route("/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
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
    return await handle_sync_request(path, request)


@app.api_route("/jobs/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def logos_service_async(path: str, request: Request):
    """
    Async job-based proxy for long running/low-priority requests.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        202 with job metadata; poll /jobs/{id} for result.
    """
    return await submit_job_request(path, request)


@app.api_route("/jobs/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def logos_service_long_async(path: str, request: Request):
    """
    Async job-based proxy for OpenAI-compatible, long running/low-priority requests.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        202 with job metadata; poll /jobs/{id} for result.
    """
    return await submit_job_request(path, request)


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: int, request: Request):
    """
    Return current state of a submitted job, including result or error when finished.

    Uses profile-based authorization - you can only view jobs created by your current profile.

    Params:
        job_id: Identifier of the async job.
        request: Incoming request

    Returns:
        Job status, result/error, and timestamps.

    Raises:
        HTTPException(401/403/404) on auth or missing job.
    """
    # Profile-based auth
    from logos.auth import authenticate_with_profile
    auth = authenticate_with_profile(dict(request.headers))

    job = JobService.fetch(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Authorization checks
    job_process_id = job.get("process_id")
    job_profile_id = job.get("profile_id")

    # 1. Job must belong to this process
    if job_process_id != auth.process_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this job")

    # 2. Job must belong to this profile
    if job_profile_id != auth.profile_id:
        raise HTTPException(
            status_code=403,
            detail="Job belongs to a different profile. Use the correct use_profile header."
        )

    return {
        "job_id": job_id,
        "status": job["status"],
        "result": job["result_payload"] if job["status"] == JobStatus.SUCCESS.value else None,
        "error": job["error_message"] if job["status"] == JobStatus.FAILED.value else None,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "profile_id": job_profile_id,
    }


@app.post("/logosdb/latest_requests")
async def latest_requests(request: Request):
    """
    Fetch the latest 10 requests for the dashboard stack.
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    with DBManager() as db:
        payload, status = db.get_latest_requests(logos_key, limit=10)
        return JSONResponse(content=payload, status_code=status)


@app.options("/logosdb/latest_requests")
async def latest_requests_options():
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
    )


# ============================================================================
# WEBSOCKET: Unified stats stream  (/ws/stats)
# ============================================================================
# Replaces the three polling HTTP calls from the statistics page with a single
# persistent WebSocket connection that pushes lightweight delta updates.
#
# Protocol (server → client):
#   { "type": "vram",     "payload": <same shape as GET /logosdb/get_ollama_vram_stats> }
#   { "type": "requests", "payload": <same shape as POST /logosdb/latest_requests> }
#
# Protocol (client → server):
#   { "action": "set_vram_day", "day": "2025-06-15" }  – change the VRAM day filter
#   { "action": "ping" }                                – keepalive (server replies pong)
#
# Auth: pass `?key=<logos_key>` as a query parameter when opening the socket.
# ============================================================================

_ws_stats_connections: Set[WebSocket] = set()


def _build_vram_signature(providers: list) -> str:
    """Deterministic signature of VRAM provider data for change detection."""
    parts = []
    for p in sorted(providers, key=lambda x: x.get("name", "")):
        data = p.get("data", [])
        last = data[-1] if data else {}
        models_str = "|".join(
            f"{m.get('name', '')}:{m.get('size_vram_mb', m.get('size_vram', ''))}"
            for m in (last.get("loaded_models") or [])
        ) if isinstance(last.get("loaded_models"), list) else ""
        parts.append(
            f"{p.get('name', '')}::{last.get('timestamp', '')}::"
            f"{last.get('used_vram_mb', last.get('vram_mb', ''))}::"
            f"{last.get('remaining_vram_mb', '')}::"
            f"{last.get('total_vram_mb', '')}::{models_str}"
        )
    return "||".join(parts)


def _requests_signature(requests_list: list) -> str:
    """Quick hash of request IDs + statuses + timestamps for change detection."""
    parts = []
    for r in requests_list:
        rid = str(r.get("request_id", ""))
        status = str(r.get("status", ""))
        sched = str(r.get("scheduled_ts", ""))
        done = str(r.get("request_complete_ts", ""))
        parts.append(f"{rid}:{status}:{sched}:{done}")
    return ",".join(parts)


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime.datetime]:
    """Parse an ISO timestamp into UTC datetime (or return None on invalid input)."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _default_timeline_window() -> Tuple[str, str, int]:
    """Default timeline window: trailing 30 days, target 120 buckets."""
    end_dt = datetime.datetime.now(datetime.timezone.utc)
    start_dt = end_dt - datetime.timedelta(days=30)
    return start_dt.isoformat(), end_dt.isoformat(), 120


@app.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket):
    """
    Unified WebSocket endpoint for statistics page.
    Streams VRAM snapshots and latest-requests with change detection so only
    actual updates are pushed.
    """
    # --- Auth via query param ---
    key = websocket.query_params.get("key", "")
    if not key:
        await websocket.close(code=4001, reason="Missing key query parameter")
        return

    try:
        logos_key, _ = authenticate_logos_key({"logos_key": key})
    except HTTPException:
        await websocket.close(code=4003, reason="Invalid logos key")
        return

    await websocket.accept()
    _ws_stats_connections.add(websocket)
    logger.info("[ws/stats] Client connected (%d total)", len(_ws_stats_connections))

    # Per-connection state
    vram_day: Optional[str] = None  # Will be set by client or default to today
    prev_vram_sig = ""
    prev_req_sig = ""

    async def _push_vram():
        nonlocal prev_vram_sig, vram_day
        day = vram_day or _today_utc()
        try:
            with DBManager() as db:
                payload, status = db.get_ollama_vram_stats(logos_key, day=day, bucket_seconds=5)
            if status == 200 and payload.get("providers"):
                sig = _build_vram_signature(payload["providers"])
                if sig != prev_vram_sig:
                    prev_vram_sig = sig
                    await websocket.send_json({"type": "vram", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats] VRAM push error: %s", exc)

    async def _push_requests():
        nonlocal prev_req_sig
        try:
            with DBManager() as db:
                payload, status = db.get_latest_requests(logos_key, limit=10)
            if status == 200:
                reqs = payload.get("requests", [])
                sig = _requests_signature(reqs)
                if sig != prev_req_sig:
                    prev_req_sig = sig
                    await websocket.send_json({"type": "requests", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats] Requests push error: %s", exc)

    # Background push loop
    async def _push_loop():
        tick = 0
        while True:
            try:
                # Push latest requests every 2s, VRAM every 5s
                await _push_requests()
                if tick % 5 == 0:
                    await _push_vram()
                tick += 1
                await asyncio.sleep(1)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as exc:
                logger.warning("[ws/stats] Push loop error: %s", exc)
                await asyncio.sleep(2)

    push_task = asyncio.create_task(_push_loop())

    try:
        # Listen for client messages (day changes, pings)
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            if action == "set_vram_day":
                new_day = msg.get("day")
                if new_day and isinstance(new_day, str):
                    vram_day = new_day
                    prev_vram_sig = ""  # Force re-push on day change
                    await _push_vram()
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        push_task.cancel()
        _ws_stats_connections.discard(websocket)
        logger.info("[ws/stats] Client disconnected (%d remaining)", len(_ws_stats_connections))


_ws_stats_v2_connections: Set[WebSocket] = set()


@app.websocket("/ws/stats/v2")
async def ws_stats_v2(websocket: WebSocket):
    """
    Incremental websocket stream for statistics (v2).

    Messages (server -> client):
      - vram_init: full VRAM day snapshot with cursor
      - vram_delta: only new VRAM rows since cursor
      - timeline_init: request_event_stats payload for selected range
      - timeline_delta: enqueue-event deltas since cursor
      - requests: latest requests list (same shape as v1)
      - pong

    Client init options:
      - timeline_deltas (bool, default true): when false, the server skips
        periodic timeline delta polling for this connection.
    """
    key = websocket.query_params.get("key", "")
    if not key:
        await websocket.close(code=4001, reason="Missing key query parameter")
        return

    try:
        logos_key, _ = authenticate_logos_key({"logos_key": key})
    except HTTPException:
        await websocket.close(code=4003, reason="Invalid logos key")
        return

    await websocket.accept()
    _ws_stats_v2_connections.add(websocket)
    logger.info("[ws/stats/v2] Client connected (%d total)", len(_ws_stats_v2_connections))

    vram_day: str = "all"
    vram_cursor: int = 0

    timeline_start_iso, timeline_end_iso, timeline_target_buckets = _default_timeline_window()
    timeline_window_seconds = 30 * 24 * 3600.0
    timeline_bucket_seconds = 60
    timeline_live = True
    timeline_deltas_enabled = False
    timeline_cursor_ts = timeline_end_iso
    timeline_cursor_request_id = ""

    prev_req_sig = ""

    def _coerce_bool(value: Any, default: bool = True) -> bool:
        """Best-effort boolean parser for websocket client flags."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default

    def _set_timeline_state(start_iso: str, end_iso: str, target_buckets: Any) -> Tuple[bool, Optional[str]]:
        nonlocal timeline_start_iso, timeline_end_iso
        nonlocal timeline_target_buckets, timeline_window_seconds
        nonlocal timeline_live, timeline_cursor_ts, timeline_cursor_request_id

        start_dt = _parse_iso_utc(start_iso)
        end_dt = _parse_iso_utc(end_iso)
        if not start_dt or not end_dt:
            return False, "Invalid start/end timestamp format"
        if start_dt >= end_dt:
            return False, "Timeline start must be before end"

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if end_dt > now_dt:
            end_dt = now_dt
            if start_dt >= end_dt:
                start_dt = end_dt - datetime.timedelta(minutes=1)

        timeline_start_iso = start_dt.isoformat()
        timeline_end_iso = end_dt.isoformat()
        try:
            parsed_target_buckets = int(target_buckets or 120)
        except (TypeError, ValueError):
            parsed_target_buckets = 120

        timeline_target_buckets = max(1, parsed_target_buckets)
        timeline_window_seconds = (end_dt - start_dt).total_seconds()
        timeline_live = (now_dt - end_dt) <= datetime.timedelta(minutes=2)
        timeline_cursor_ts = timeline_end_iso
        timeline_cursor_request_id = ""
        return True, None

    async def _send_vram_init() -> None:
        nonlocal vram_cursor
        try:
            with DBManager() as db:
                payload, status = db.get_ollama_vram_deltas(
                    logos_key,
                    day=vram_day,
                    after_snapshot_id=0,
                )
            if status != 200:
                await websocket.send_json({
                    "type": "vram_init",
                    "payload": {"error": payload.get("error", "Failed to load VRAM data")},
                })
                return
            vram_cursor = int(payload.get("last_snapshot_id") or 0)
            await websocket.send_json({"type": "vram_init", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] VRAM init error: %s", exc)
            await websocket.send_json({
                "type": "vram_init",
                "payload": {"error": "Failed to load VRAM data"},
            })

    async def _push_vram_delta() -> None:
        nonlocal vram_cursor
        try:
            with DBManager() as db:
                payload, status = db.get_ollama_vram_deltas(
                    logos_key,
                    day=vram_day,
                    after_snapshot_id=vram_cursor,
                )
            if status != 200:
                return

            new_cursor = int(payload.get("last_snapshot_id") or vram_cursor)
            providers = payload.get("providers") or []
            if providers:
                vram_cursor = new_cursor
                await websocket.send_json({"type": "vram_delta", "payload": payload})
            elif new_cursor > vram_cursor:
                vram_cursor = new_cursor
        except Exception as exc:
            logger.warning("[ws/stats/v2] VRAM delta push error: %s", exc)

    async def _send_timeline_init() -> None:
        nonlocal timeline_bucket_seconds
        nonlocal timeline_cursor_ts, timeline_cursor_request_id
        try:
            with DBManager() as db:
                payload, status = db.get_request_event_stats(
                    logos_key,
                    start_date=timeline_start_iso,
                    end_date=timeline_end_iso,
                    target_buckets=timeline_target_buckets,
                )
                events_payload, events_status = db.get_request_enqueues_in_range(
                    logos_key,
                    start_ts=timeline_start_iso,
                    end_ts=timeline_end_iso,
                    limit=200000,
                )
            if status != 200:
                await websocket.send_json({
                    "type": "timeline_init",
                    "payload": {"error": payload.get("error", "Failed to load timeline data")},
                })
                return

            timeline_bucket_seconds = int(payload.get("bucketSeconds") or timeline_bucket_seconds)
            timeline_cursor_ts = timeline_end_iso
            timeline_cursor_request_id = ""
            payload["cursor"] = {
                "enqueue_ts": timeline_cursor_ts,
                "request_id": timeline_cursor_request_id,
            }
            payload["events"] = events_payload.get("events", []) if events_status == 200 else []
            await websocket.send_json({"type": "timeline_init", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] Timeline init error: %s", exc)
            await websocket.send_json({
                "type": "timeline_init",
                "payload": {"error": "Failed to load timeline data"},
            })

    async def _push_timeline_delta() -> None:
        nonlocal timeline_start_iso, timeline_end_iso
        nonlocal timeline_cursor_ts, timeline_cursor_request_id
        if not timeline_live:
            return

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        until_iso = now_dt.isoformat()

        try:
            with DBManager() as db:
                payload, status = db.get_request_enqueues_deltas(
                    logos_key,
                    after_enqueue_ts=timeline_cursor_ts,
                    after_request_id=timeline_cursor_request_id,
                    until_ts=until_iso,
                    limit=5000,
                )
            if status != 200:
                return

            cursor = payload.get("cursor") or {}
            if cursor.get("enqueue_ts") is not None:
                timeline_cursor_ts = cursor.get("enqueue_ts")
            if cursor.get("request_id") is not None:
                timeline_cursor_request_id = str(cursor.get("request_id") or "")

            events = payload.get("events") or []
            if not events:
                return

            timeline_end_iso = until_iso
            start_dt = now_dt - datetime.timedelta(seconds=timeline_window_seconds)
            timeline_start_iso = start_dt.isoformat()

            await websocket.send_json({
                "type": "timeline_delta",
                "payload": {
                    "events": events,
                    "cursor": {
                        "enqueue_ts": timeline_cursor_ts,
                        "request_id": timeline_cursor_request_id,
                    },
                    "bucketSeconds": timeline_bucket_seconds,
                    "range": {
                        "start": timeline_start_iso,
                        "end": timeline_end_iso,
                    },
                },
            })
        except Exception as exc:
            logger.warning("[ws/stats/v2] Timeline delta push error: %s", exc)

    async def _push_requests(force: bool = False) -> None:
        nonlocal prev_req_sig
        try:
            with DBManager() as db:
                payload, status = db.get_latest_requests(logos_key, limit=10)
            if status != 200:
                return

            reqs = payload.get("requests", [])
            sig = _requests_signature(reqs)
            if force or sig != prev_req_sig:
                prev_req_sig = sig
                await websocket.send_json({"type": "requests", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] Requests push error: %s", exc)

    async def _push_loop():
        tick = 0
        while True:
            try:
                if tick % 2 == 0:
                    await _push_requests()
                    if timeline_deltas_enabled:
                        await _push_timeline_delta()
                if tick % 5 == 0:
                    await _push_vram_delta()

                tick += 1
                await asyncio.sleep(1)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as exc:
                logger.warning("[ws/stats/v2] Push loop error: %s", exc)
                await asyncio.sleep(2)

    push_task = asyncio.create_task(_push_loop())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            if action == "init":
                requested_day = msg.get("vram_day")
                if isinstance(requested_day, str) and requested_day.strip():
                    vram_day = requested_day
                vram_cursor = 0
                timeline_deltas_enabled = _coerce_bool(msg.get("timeline_deltas"), default=True)

                timeline_cfg = msg.get("timeline") or {}
                start_iso = timeline_cfg.get("start")
                end_iso = timeline_cfg.get("end")
                target_buckets = timeline_cfg.get("target_buckets", 120)
                if not start_iso or not end_iso:
                    start_iso, end_iso, target_buckets = _default_timeline_window()
                ok, err_msg = _set_timeline_state(str(start_iso), str(end_iso), target_buckets)
                if not ok:
                    await websocket.send_json({
                        "type": "timeline_init",
                        "payload": {"error": err_msg or "Invalid timeline range"},
                    })
                else:
                    await _send_timeline_init()

                await _send_vram_init()
                await _push_requests(force=True)
            elif action == "set_vram_day":
                new_day = msg.get("day")
                if isinstance(new_day, str) and new_day.strip():
                    vram_day = new_day
                    vram_cursor = 0
                    await _send_vram_init()
            elif action == "set_timeline_range":
                start_iso = msg.get("start")
                end_iso = msg.get("end")
                target_buckets = msg.get("target_buckets", 120)
                ok, err_msg = _set_timeline_state(str(start_iso), str(end_iso), target_buckets)
                if not ok:
                    await websocket.send_json({
                        "type": "timeline_init",
                        "payload": {"error": err_msg or "Invalid timeline range"},
                    })
                else:
                    await _send_timeline_init()
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        push_task.cancel()
        _ws_stats_v2_connections.discard(websocket)
        logger.info("[ws/stats/v2] Client disconnected (%d remaining)", len(_ws_stats_v2_connections))


def _today_utc() -> str:
    """Return today's date as YYYY-MM-DD in UTC."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

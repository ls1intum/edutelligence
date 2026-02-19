import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Set, Tuple, Optional
import grpc
from fastapi import FastAPI, Request, HTTPException
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
from logos.temp_providers.registry import TempProviderRegistry
from logos.temp_providers.health_monitor import HealthMonitor
from logos.temp_providers.discovery import discover_models
from scripts import setup_proxy

logger = logging.getLogger("LogosLogger")
_grpc_server = None
_background_tasks: Set[asyncio.Task] = set()
_ollama_monitor: Optional[OllamaProviderMonitor] = None
_temp_health_monitor: Optional[HealthMonitor] = None

OLLAMA_PROCESSING_TIMEOUT_S = 60


def _get_processing_timeout_s(scheduling_stats: Optional[Dict[str, Any]]) -> Optional[int]:
    if scheduling_stats and scheduling_stats.get("provider_type") == "ollama":
        return OLLAMA_PROCESSING_TIMEOUT_S
    return None


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

    # Start temp-provider health monitor
    global _temp_health_monitor
    _temp_health_monitor = HealthMonitor(interval_s=30, auto_remove_after_s=300)
    _temp_health_monitor.start()
    logger.info("Temp-provider health monitor started")

    # Start gRPC server
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(_pipeline), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()

    yield

    # Shutdown logic
    # Stop temp-provider health monitor
    if _temp_health_monitor:
        await _temp_health_monitor.stop()

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
                _azure_facade.register_model(
                    model_id=model_id,
                    provider_name=provider_name,
                    model_name=model_name,
                    model_endpoint=model_info["endpoint"],
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
                    "endpoint": tpl["endpoint"],
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
        processing_timeout_s = _get_processing_timeout_s(scheduling_stats)

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

            if processing_timeout_s:
                async with asyncio.timeout(processing_timeout_s):
                    async for chunk in _pipeline.executor.execute_streaming(
                        context.forward_url,
                        headers,
                        prepared_payload,
                        on_headers=process_headers,
                    ):
                        yield chunk

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
            else:
                async for chunk in _pipeline.executor.execute_streaming(
                    context.forward_url,
                    headers,
                    prepared_payload,
                    on_headers=process_headers,
                ):
                    yield chunk

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
        except asyncio.TimeoutError:
            timed_out = True
            error_message = f"Processing timeout after {processing_timeout_s}s"
            logger.warning("Streaming request timed out after %ss (model_id=%s)", processing_timeout_s, model_id)
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
                if first_chunk:
                    response_payload = first_chunk.copy()
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

        processing_timeout_s = _get_processing_timeout_s(scheduling_stats)
        timed_out = False
        error_message = None

        try:
            if processing_timeout_s:
                exec_result = await asyncio.wait_for(
                    _pipeline.executor.execute_sync(context.forward_url, headers, prepared_payload),
                    timeout=processing_timeout_s,
                )
            else:
                exec_result = await _pipeline.executor.execute_sync(context.forward_url, headers, prepared_payload)
        except asyncio.TimeoutError:
            timed_out = True
            error_message = f"Processing timeout after {processing_timeout_s}s"
            logger.warning("Sync request timed out after %ss (model_id=%s)", processing_timeout_s, model_id)
            exec_result = ExecutionResult(
                success=False,
                response={"error": error_message},
                error=error_message,
                usage={},
                is_streaming=False,
            )

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
                db.set_response_payload(
                    log_id,
                    response_payload,
                    provider_id,
                    model_id,
                    usage_tokens,
                    policy_id,
                    classification_stats,
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
                if first_chunk:
                    response_payload = first_chunk.copy()
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


async def _execute_temp_provider_request(
    provider,
    body: Dict[str, Any],
    headers: Dict[str, str],
    path: str,
    is_async_job: bool,
):
    """
    Forward a request to a temporary provider, handling errors gracefully.

    If the provider is unreachable it is marked unhealthy and a 503 is returned.
    """
    from logos.temp_providers.registry import TempProvider, TempProviderRegistry
    import httpx as _httpx

    prov: TempProvider = provider
    forward_url = prov.url.rstrip("/") + "/v1/" + path

    fwd_headers: Dict[str, str] = {"Content-Type": "application/json"}
    if prov.auth_key:
        fwd_headers["Authorization"] = f"Bearer {prov.auth_key}"

    payload = {**body}
    if "stream" not in payload:
        payload["stream"] = False

    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(connect=10, read=120, write=10, pool=10)) as client:
            resp = await client.post(forward_url, headers=fwd_headers, json=payload)
            resp.raise_for_status()
            result = resp.json()
            status_code = resp.status_code
    except _httpx.HTTPStatusError as exc:
        # Upstream returned a non-2xx HTTP response — forward it without marking unhealthy.
        upstream_resp = exc.response
        status_code = upstream_resp.status_code
        try:
            result = upstream_resp.json()
        except ValueError:
            result = {"error": upstream_resp.text}
        logger.info(
            "Temp provider %s (%s) returned HTTP %s",
            prov.id, prov.name, status_code,
        )
    except _httpx.RequestError as exc:
        # Transport-level error (connect/timeout/DNS) — mark unhealthy.
        logger.warning("Temp provider %s (%s) request failed: %s", prov.id, prov.name, exc)
        TempProviderRegistry().mark_unhealthy(prov.id)
        error_payload = {"error": f"Temp provider '{prov.name}' is unreachable"}
        if is_async_job:
            return {"status_code": 503, "data": error_payload}
        raise HTTPException(status_code=503, detail=error_payload["error"])
    except Exception as exc:
        # Unexpected error — mark unhealthy.
        logger.exception("Unexpected error calling temp provider %s (%s)", prov.id, prov.name)
        TempProviderRegistry().mark_unhealthy(prov.id)
        error_payload = {"error": f"Temp provider '{prov.name}' is unreachable"}
        if is_async_job:
            return {"status_code": 503, "data": error_payload}
        raise HTTPException(status_code=503, detail=error_payload["error"])

    if is_async_job:
        return {"status_code": status_code, "data": result}
    return JSONResponse(content=result, status_code=status_code)


async def _execute_proxy_mode(
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    path: str,
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
        # Check temp providers — the model may live on an ephemeral node.
        temp_auth_token = headers.get("x-temp-provider-token") or headers.get("X-Temp-Provider-Token")
        temp_prov = TempProviderRegistry().find_provider_for_model(model_name, auth_token=temp_auth_token)
        if temp_prov is not None:
            return await _execute_temp_provider_request(
                provider=temp_prov,
                body=body,
                headers=headers,
                path=path,
                is_async_job=is_async_job,
            )
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
            return await _execute_proxy_mode(body, headers, logos_key, path, deployments, log_id, is_async_job, profile_id=profile_id)

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
# TEMPORARY PROVIDER ENDPOINTS
# ============================================================================

@app.post("/logosdb/add_temp_provider")
async def add_temp_provider(request: Request):
    """
    Register a temporary (in-memory) LLM provider.

    Request body::

        {
            "url": "https://my-mac.tunnel.dev",
            "auth_key": "optional-provider-credential",
            "name": "my-mac-lmstudio"
        }

    Returns the provider info including auto-discovered models and a unique
    ``auth_token`` that callers must present to route requests through this
    provider.
    """
    headers = dict(request.headers)
    logos_key, process_id = authenticate_logos_key(headers)

    body = await request.json()
    url = body.get("url")
    name = body.get("name", "temp-provider")
    auth_key = body.get("auth_key")

    if not url:
        raise HTTPException(status_code=400, detail="'url' is required")

    # Auto-discover models
    models = await discover_models(url, auth_key)

    registry = TempProviderRegistry()
    provider = registry.register(
        url=url,
        name=name,
        owner_process_id=process_id,
        models=models,
        auth_key=auth_key,
    )

    return JSONResponse(content=provider.to_dict(), status_code=201)


@app.delete("/logosdb/remove_temp_provider/{provider_id}")
async def remove_temp_provider(provider_id: str, request: Request):
    """Remove a temporary provider. Only the owner or root can remove."""
    headers = dict(request.headers)
    logos_key, process_id = authenticate_logos_key(headers)

    registry = TempProviderRegistry()
    provider = registry.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Temp provider not found")

    # Authorization: owner or root
    with DBManager() as db:
        is_root = db.check_authorization(logos_key)
    if provider.owner_process_id != process_id and not is_root:
        raise HTTPException(status_code=403, detail="Not authorized to remove this provider")

    registry.unregister(provider_id)
    return JSONResponse(content={"result": "removed"}, status_code=200)


@app.get("/logosdb/temp_providers")
async def list_temp_providers(request: Request):
    """
    List temporary providers with health status.

    Root sees all providers; non-root sees only their own.
    """
    headers = dict(request.headers)
    logos_key, process_id = authenticate_logos_key(headers)

    registry = TempProviderRegistry()

    with DBManager() as db:
        is_root = db.check_authorization(logos_key)

    if is_root:
        providers = registry.list_all()
    else:
        providers = registry.list_for_process(process_id)

    return JSONResponse(
        content={"providers": [p.to_dict() for p in providers]},
        status_code=200,
    )


@app.post("/logosdb/refresh_temp_provider/{provider_id}")
async def refresh_temp_provider(provider_id: str, request: Request):
    """Force re-discovery of models on a temporary provider."""
    headers = dict(request.headers)
    logos_key, process_id = authenticate_logos_key(headers)

    registry = TempProviderRegistry()
    provider = registry.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Temp provider not found")

    with DBManager() as db:
        is_root = db.check_authorization(logos_key)
    if provider.owner_process_id != process_id and not is_root:
        raise HTTPException(status_code=403, detail="Not authorized to refresh this provider")

    models = await discover_models(provider.url, provider.auth_key)
    registry.update_models(provider_id, models)

    # Re-fetch to return updated state
    updated = registry.get(provider_id)
    return JSONResponse(content=updated.to_dict() if updated else {}, status_code=200)


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

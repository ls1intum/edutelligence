import asyncio
import json
import logging
import os
import traceback
from contextlib import asynccontextmanager
from typing import Any, Dict, Set, Tuple, Optional, List

import grpc
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from logos.auth import authenticate_logos_key, _resolve_logos_key
from grpclocal import model_pb2_grpc
from grpclocal.grpc_server import LogosServicer
from logos.classification.classification_balancer import Balancer
from logos.classification.classification_manager import ClassificationManager
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.dbrequest import *
from logos.jobs.job_service import JobService, JobSubmission
from logos.responses import (
    get_client_ip,
    extract_model,
    request_setup,
    proxy_behaviour,
    extract_token_usage
)
# New Pipeline Components
from logos.pipeline.pipeline import RequestPipeline, PipelineRequest
from logos.pipeline.scheduler_interface import UtilizationAwareScheduler
from logos.pipeline.executor import Executor
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from scripts import setup_proxy

logger = logging.getLogger("LogosLogger")

# Global Components
_pipeline: Optional[RequestPipeline] = None
_queue_mgr: Optional[PriorityQueueManager] = None
_ollama_facade: Optional[OllamaSchedulingDataFacade] = None
_azure_facade: Optional[AzureSchedulingDataFacade] = None
_grpc_server = None
_background_tasks: Set[asyncio.Task] = set()

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

    # Start Pipeline
    await start_pipeline()

    # Start gRPC server
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(_pipeline), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()

    # Initial provider setup from environment variables
    DEFAULT_PROVIDER = os.getenv("PROVIDER_NAME")
    DEFAULT_BASE_URL = os.getenv("BASE_URL")
    FORMAT = '%(levelname)-8s: %(asctime)s at module %(module)-15s %(message)s'
    logging.basicConfig(format=FORMAT, level=logging.DEBUG)
    if DEFAULT_PROVIDER and len(DEFAULT_BASE_URL) > 5:
        logging.info("Creating Proxy Configuration...")
        with DBManager() as db:
            db.is_root_initialized()
        logging.info("Processing setup. Initialized: %s", str(DBManager.is_initialized()))
        if not DBManager.is_initialized():
            lk = setup_proxy.setup(DEFAULT_BASE_URL, DEFAULT_PROVIDER)
            if "error" in lk:
                logging.error("Error during proxy setup: %s", lk)
            else:
                logging.info("Created proxy configuration: %s", lk)

    yield

    # Shutdown logic
    if _grpc_server:
        await _grpc_server.stop(0)


app = FastAPI(docs_url="/docs", openapi_url="/openapi.json", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion ggf. einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # logos_key etc.
)


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
            with DBManager() as db:
                policy = db.get_policy(logos_key, int(headers["policy"]))
                if isinstance(policy, dict) and "error" in policy:
                    logger.warning(f"Failed to load policy {headers['policy']}: {policy['error']}")
                    policy = None
        except Exception as e:
            logger.warning(f"Failed to load policy from header: {e}")
            policy = None

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
    global _pipeline, _queue_mgr, _ollama_facade, _azure_facade
    
    logger.info("Initializing Request Pipeline...")

    _queue_mgr = PriorityQueueManager()

    _ollama_facade = OllamaSchedulingDataFacade(_queue_mgr, None) 
    _azure_facade = AzureSchedulingDataFacade(None)

    await _register_models_with_facades(_ollama_facade, _azure_facade)

    model_registry = _build_model_registry()
    scheduler = UtilizationAwareScheduler( # Swap in other schedulers as needed
        queue_manager=_queue_mgr,
        ollama_facade=_ollama_facade,
        azure_facade=_azure_facade,
        model_registry=model_registry
    )
    
    # 5. Executor
    executor = Executor()
    
    # 6. Classifier
    clf = classifier()
    
    # 7. Pipeline
    _pipeline = RequestPipeline(
        classifier=clf,
        scheduler=scheduler,
        executor=executor
    )
    
    logger.info("Request Pipeline Initialized. with SDI-aware scheduling")


async def _register_models_with_facades(ollama_facade: OllamaSchedulingDataFacade, azure_facade: AzureSchedulingDataFacade):
    """Register all models with their respective SDI facades."""
    with DBManager() as db:
        # Get all models and their providers
        models_data = db.get_all_models_data()
        
        for model_data in models_data:
            model_id = model_data[0]
            model_name = model_data[1]
            
            provider = db.get_provider_to_model(model_id)
            if not provider:
                continue
            
            provider_name = provider["name"].lower()
            provider_id = provider["id"]
            
            # Get SDI config
            provider_config = db.get_provider_config(provider_id) or {}
            
            if "ollama" in provider_name or "openwebui" in provider_name:
                _ollama_facade.register_model(
                    model_id=model_id,
                    provider_name=provider_name,
                    ollama_admin_url=provider_config.get("ollama_admin_url"),
                    model_name=model_name,
                    total_vram_mb=provider_config.get("total_vram_mb", 65536),
                    provider_id=provider_id,
                )
            elif "azure" in provider_name:
                model_info = db.get_model(model_id)
                if model_info:
                    _azure_facade.register_model(
                        model_id=model_id,
                        provider_name=provider_name,
                        model_name=model_name,
                        model_endpoint=model_info["endpoint"],
                        provider_id=provider_id,
                    )


def _build_model_registry() -> Dict[int, str]:
    """Build mapping of model_id -> provider_type."""
    registry = {}
    with DBManager() as db:
        for model_id in db.get_all_models():
            provider = db.get_provider_to_model(model_id)
            if provider:
                name = provider["name"].lower()
                if "ollama" in name or "openwebui" in name:
                    registry[model_id] = "ollama"
                elif "azure" in name:
                    registry[model_id] = "azure"
                else:
                    registry[model_id] = "cloud"  # Generic cloud
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
                    "api_id": tpl["api_id"],
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


@app.post("/logosdb/get_api_id")
async def get_api_id(data: GetAPIIdRequest):
    with DBManager() as db:
        return db.get_api_id(data.logos_key, data.api_key)


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


@app.api_route("/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def work(request: Request, path: str = None):
    """
    Dynamic proxy for LLM API endpoints.
    Supports two modes:
    - PROXY MODE: Direct forwarding to provider (no classification/scheduling)
    - RESOURCE MODE: Classification + scheduling with SDI-aware pipeline

    :param request: FastAPI Request object containing headers, body, and client metadata
    :param path: API endpoint path (e.g., 'chat/completions', 'completions', 'embeddings')
    :return: StreamingResponse for streaming requests, JSONResponse for synchronous requests
    """

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract headers and auth (using auth.py helper)
    headers = dict(request.headers)
    logos_key = _resolve_logos_key(headers, required=False)

    # Log request
    log_id = None
    if logos_key:
        with DBManager() as db:
            r, c = db.get_process_id(logos_key)
            if c == 200:
                r_log, c_log = db.log_usage(int(r["result"]), get_client_ip(request), body, headers)
                if c_log == 200:
                    log_id = int(r_log["log-id"])

    # Check if we should use proxy mode or resource mode
    models = request_setup(headers, logos_key)

    # PROXY MODE: Direct forwarding without classification
    if not models or "proxy" in headers:
        with DBManager() as db:
            providers = db.get_providers(logos_key)

        out = proxy_behaviour(headers, providers, path)
        if isinstance(out[0], dict) and "error" in out[0]:
            raise HTTPException(status_code=out[1], detail=out[0]["error"])
        proxy_headers, forward_url, provider_id = out
        model_id = None
        policy_id = -1
        classified = {}

        # Forward request (streaming or sync) using executor
        try:
            if body.get("stream"):
                return _proxy_streaming_response(
                    forward_url, proxy_headers, body,
                    log_id, provider_id, model_id, policy_id, classified
                )
            else:
                response = await _proxy_sync_response(
                    forward_url, proxy_headers, body,
                    log_id, provider_id, model_id, policy_id, classified
                )
                return response
        except Exception as e:
            logger.error(f"Proxy mode request failed: {e}")
            raise HTTPException(status_code=500, detail=f"Provider error: {str(e)}")

    # RESOURCE MODE: Pipeline with classification and scheduling
    else:
        # Resolve allowed models from request (None means "use all known models")
        allowed_models = None
        requested_model = body.get("model")
        if requested_model:
            for m in _pipeline.classifier.models:
                if m["name"] == requested_model:
                    allowed_models = [m["id"]]
                    break

            if allowed_models is None:
                raise HTTPException(status_code=404, detail=f"Model '{requested_model}' not found")

        # Extract policy from headers and model string
        policy = _extract_policy(headers, logos_key, body)

        # Create Pipeline Request
        pipeline_req = PipelineRequest(
            logos_key=logos_key or "anon",
            payload=body,
            headers=headers,
            policy=policy,
            allowed_models=allowed_models
        )

        # Process
        result = await _pipeline.process(pipeline_req)

        if not result.success:
            raise HTTPException(status_code=503, detail=result.error or "Pipeline processing failed")

        # Execute and Respond
        try:
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
            _pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status="error",
                error_message=str(e)
            )
            raise e



def _streaming_response(context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats=None):
    """Build streaming response using executor."""
    from fastapi.responses import StreamingResponse
    
    async def streamer():
        full_text = ""
        first_chunk = None
        last_chunk = None
        error_message = None

        try:
            def process_headers(headers: dict):
                try:
                    _pipeline.update_provider_stats(model_id, headers)
                except Exception:
                    pass

            async for chunk in _pipeline.executor.execute_streaming(context, payload, on_headers=process_headers):
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
                status = "error" if error_message else "success"
                
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
                        scheduling_stats.get("request_id")
                    )
                except Exception as e:
                    logger.error(f"Failed to release scheduler resources: {e}")
    
    return StreamingResponse(streamer(), media_type="text/event-stream")


async def _sync_response(context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats=None):
    """Execute sync request and return response."""
    from fastapi.responses import JSONResponse
    
    try:
        exec_result = await _pipeline.executor.execute_sync(context, payload)

        # Update rate limits from response headers
        if exec_result.headers:
            try:
                _pipeline.update_provider_stats(model_id, exec_result.headers)
            except Exception:
                pass

        response_payload = exec_result.response
        if not exec_result.success and not response_payload and exec_result.error:
            response_payload = {"error": exec_result.error}
            logger.error(f"Request failed: {exec_result.error}")

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
            status = "success" if exec_result.success else "error"
            _pipeline.record_completion(
                request_id=scheduling_stats.get("request_id"),
                result_status=status,
                error_message=exec_result.error if not exec_result.success else None,
                cold_start=scheduling_stats.get("is_cold_start")
            )
        
        return JSONResponse(content=exec_result.response, status_code=200 if exec_result.success else 500)

    finally:
        if scheduling_stats and scheduling_stats.get("request_id"):
            try:
                _pipeline.scheduler.release(
                    model_id,
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
            async for chunk in _pipeline.executor.execute_direct_streaming(
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
                                policy_id: int, classified: dict):
    """
    Build synchronous response for PROXY MODE using executor.
    """
    from fastapi.responses import JSONResponse

    exec_result = await _pipeline.executor.execute_direct_sync(
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

    return JSONResponse(content=response_payload, status_code=200 if exec_result.success else 500)


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def logos_service(path: str, request: Request):
    """
    Dynamic proxy for AI endpoints.
    Supports both PROXY and RESOURCE modes with streaming.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        Upstream response (streaming or sync) based on request.
    """
    # Auth is REQUIRED for /v1 endpoint
    headers = dict(request.headers)
    logos_key, process_id = authenticate_logos_key(headers)

    # Parse body
    raw_body = await request.body()
    try:
        body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    client_ip = get_client_ip(request)

    # Log request
    log_id = None
    with DBManager() as db:
        r_log, c_log = db.log_usage(process_id, client_ip, body, headers)
        if c_log == 200:
            log_id = int(r_log["log-id"])

    # Determine mode: PROXY or RESOURCE
    models = request_setup(headers, logos_key)
    if isinstance(models, tuple) and len(models) == 2 and isinstance(models[0], dict) and "error" in models[0]:
        raise HTTPException(status_code=models[1], detail=models[0]["error"])

    # PROXY MODE: Direct forwarding
    if not models:
        with DBManager() as db:
            providers = db.get_providers(logos_key)

        out = proxy_behaviour(headers, providers, path)
        if isinstance(out[0], dict) and "error" in out[0]:
            raise HTTPException(status_code=out[1], detail=out[0]["error"])

        proxy_headers, forward_url, provider_id = out
        model_id = None
        policy_id = -1
        classified = {}

        # Forward request (streaming or sync) using executor
        try:
            if body.get("stream"):
                return _proxy_streaming_response(
                    forward_url, proxy_headers, body,
                    log_id, provider_id, model_id, policy_id, classified
                )
            else:
                response = await _proxy_sync_response(
                    forward_url, proxy_headers, body,
                    log_id, provider_id, model_id, policy_id, classified
                )
                return response
        except Exception as e:
            logger.error(f"Proxy mode request failed: {e}")
            raise HTTPException(status_code=500, detail=f"Provider error: {str(e)}")

    # RESOURCE MODE: Pipeline with classification and scheduling
    else:
        # Resolve allowed models from request
        allowed_models = None
        requested_model = body.get("model")
        if requested_model:
            for m in _pipeline.classifier.models:
                if m["name"] == requested_model:
                    allowed_models = [m["id"]]
                    break

            if allowed_models is None:
                raise HTTPException(status_code=404, detail=f"Model '{requested_model}' not found")

        # Extract policy
        policy = _extract_policy(headers, logos_key, body)

        # Create Pipeline Request
        pipeline_req = PipelineRequest(
            logos_key=logos_key or "anon",
            payload=body,
            headers=headers,
            policy=policy,
            allowed_models=allowed_models
        )

        # Process
        result = await _pipeline.process(pipeline_req)

        if not result.success:
            raise HTTPException(status_code=503, detail=result.error or "Pipeline processing failed")

        # Execute and Respond
        try:
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
            _pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status="error",
                error_message=str(e)
            )
            raise e


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

    Params:
        job_id: Identifier of the async job.
        request: Incoming request

    Returns:
        Job status, result/error, and timestamps.

    Raises:
        HTTPException(401/403/404) on auth or missing job.
    """
    _, process_id = authenticate_logos_key(dict(request.headers))
    job = JobService.fetch(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job_process_id = job.get("process_id")
    if job_process_id != process_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this job")
    return {
        "job_id": job_id,
        "status": job["status"],
        "result": job["result_payload"] if job["status"] == JobStatus.SUCCESS.value else None,
        "error": job["error_message"] if job["status"] == JobStatus.FAILED.value else None,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


async def authenticate_and_parse_request(request: Request) -> Tuple[Dict[str, str], str, int, Dict[str, Any], str]:
    """
    Authenticate the request and parse headers/body/client IP.

    Params:
        request: Incoming request.

    Returns:
        headers dict, logos key, process_id, JSON payload as dict, client IP.

    Raises:
        HTTPException(400/401): On auth failure or invalid JSON payload.
    """
    headers = dict(request.headers)
    logos_key, process_id = authenticate_logos_key(headers)
    raw_body = await request.body()
    try:
        json_data = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from err
    if json_data is None:
        json_data = {}
    if not isinstance(json_data, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")
    client_ip = get_client_ip(request)
    return headers, logos_key, process_id, json_data, client_ip


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
    headers, logos_key, process_id, json_data, client_ip = await authenticate_and_parse_request(request)
    # Persist job and run it asynchronously
    job_payload = JobSubmission(
        path=path,
        method=request.method,
        headers=headers,
        body=json_data,
        client_ip=client_ip,
        process_id=process_id,
    )
    job_id = JobService.create_job(job_payload)
    status_url = str(request.url_for("get_job_status", job_id=job_id))
    # Fire-and-forget: run the heavy proxy/classification pipeline off the request path.
    task = asyncio.create_task(process_job(job_id, path, headers, dict(json_data), client_ip, logos_key, process_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(status_code=202, content={"job_id": job_id, "status_url": status_url})


async def process_job(job_id: int, path: str, headers: Dict[str, str], json_data: Dict[str, Any], client_ip: str,
                      logos_key: str, process_id: int):
    """
    Execute a job and persist success or failure.
    """
    try:
        JobService.mark_running(job_id)
        result = await execute_proxy_job(path, headers, json_data, client_ip, logos_key=logos_key,
                                         process_id=process_id)
        JobService.mark_success(job_id, result)
    # Exception while processing the job is caught and persisted in the database
    except Exception as e:
        logging.exception("Job %s failed", job_id)
        JobService.mark_failed(job_id, str(e))
        return {"status_code": 500, "data": {"error": "Job failed"}}
    return result


async def execute_proxy_job(path: str, headers: Dict[str, str], json_data: Dict[str, Any], client_ip: str,
                            logos_key: str, process_id: int) -> Dict[str, Any]:
    """
    Execute the proxy workflow using either PROXY MODE or RESOURCE MODE pipeline.
    Force non-streaming for async job execution.

    Returns:
        Serializable dict result with status_code and data.
    """
    headers = headers or dict()
    json_data = json_data or dict()

    # Log usage
    usage_id = None
    with DBManager() as db:
        r, c = db.log_usage(process_id, client_ip, json_data, headers)
        if c != 200:
            logging.info("Error while logging a request: %s", r)
        else:
            usage_id = int(r["log-id"])

    # Determine mode
    models = request_setup(headers, logos_key)
    if isinstance(models, tuple) and len(models) == 2 and isinstance(models[0], dict) and "error" in models[0]:
        status_code = models[1] if isinstance(models[1], int) else 500
        return {"status_code": status_code, "data": models[0]}

    # Force non-streaming for jobs
    json_data["stream"] = False

    # PROXY MODE
    if not models:
        with DBManager() as db:
            providers = db.get_providers(logos_key)
        out = proxy_behaviour(headers, providers, path)
        if isinstance(out[0], dict) and "error" in out[0]:
            status_code = out[1] if len(out) > 1 else 500
            return {"status_code": status_code, "data": out[0]}

        proxy_headers, forward_url, provider_id = out
        model_id = None
        policy_id = -1
        classified = {}

        # Execute via executor (non-streaming for jobs)
        exec_result = await _pipeline.executor.execute_direct_sync(
            forward_url, proxy_headers, json_data
        )

        # Log completion
        if usage_id and exec_result.response:
            usage = exec_result.response.get("usage", {})
            usage_tokens = extract_token_usage(usage) if usage else {}

            with DBManager() as db:
                db.set_time_at_first_token(usage_id)
                db.set_response_timestamp(usage_id)
                db.set_response_payload(
                    usage_id,
                    exec_result.response,
                    provider_id,
                    model_id,
                    usage_tokens,
                    policy_id,
                    classified
                )

        response_payload = exec_result.response
        if not exec_result.success and not response_payload and exec_result.error:
            response_payload = {"error": exec_result.error}

        return {"status_code": 200 if exec_result.success else 500, "data": response_payload}

    # RESOURCE MODE - use pipeline
    else:
        # Resolve allowed models from request
        allowed_models = None
        requested_model = json_data.get("model")
        if requested_model:
            for m in _pipeline.classifier.models:
                if m["name"] == requested_model:
                    allowed_models = [m["id"]]
                    break
            if allowed_models is None:
                return {"status_code": 404, "data": {"error": f"Model '{requested_model}' not found"}}

        # Extract policy
        policy = _extract_policy(headers, logos_key, json_data)

        # Create Pipeline Request
        pipeline_req = PipelineRequest(
            logos_key=logos_key or "anon",
            payload=json_data,
            headers=headers,
            policy=policy,
            allowed_models=allowed_models
        )

        # Process through pipeline
        result = await _pipeline.process(pipeline_req)

        if not result.success:
            return {"status_code": 503, "data": {"error": result.error or "Pipeline processing failed"}}

        # Execute (non-streaming)
        try:
            exec_result = await _pipeline.executor.execute_sync(result.execution_context, json_data)

            # Update provider stats from response headers
            if exec_result.headers:
                try:
                    _pipeline.update_provider_stats(result.model_id, exec_result.headers)
                except Exception:
                    pass

            response_payload = exec_result.response
            if not exec_result.success and not response_payload and exec_result.error:
                response_payload = {"error": exec_result.error}

            # Log completion
            if usage_id:
                usage = response_payload.get("usage", {}) if response_payload else {}
                usage_tokens = extract_token_usage(usage) if usage else {}

                with DBManager() as db:
                    db.set_response_payload(
                        usage_id,
                        response_payload,
                        result.provider_id,
                        result.model_id,
                        usage_tokens,
                        -1,  # policy_id
                        result.classification_stats,
                        queue_depth_at_arrival=result.scheduling_stats.get("queue_depth_at_arrival"),
                        utilization_at_arrival=result.scheduling_stats.get("utilization_at_arrival")
                    )

            # Record completion
            status = "success" if exec_result.success else "error"
            _pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status=status,
                error_message=exec_result.error if not exec_result.success else None,
                cold_start=result.scheduling_stats.get("is_cold_start")
            )

            return {"status_code": 200 if exec_result.success else 500, "data": response_payload}

        finally:
            # Release scheduler resources
            if result.scheduling_stats and result.scheduling_stats.get("request_id"):
                try:
                    _pipeline.scheduler.release(
                        result.model_id,
                        result.scheduling_stats.get("request_id")
                    )
                except Exception as e:
                    logger.error(f"Failed to release scheduler resources: {e}")


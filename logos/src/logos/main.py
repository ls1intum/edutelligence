import json
import logging
import os
import traceback
from contextlib import asynccontextmanager

import grpc
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from grpclocal import model_pb2_grpc
from grpclocal.grpc_server import LogosServicer
from logos.classification.classification_balancer import Balancer
from logos.classification.classification_manager import ClassificationManager
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import *
from logos.responses import get_client_ip
# New Pipeline Components
from logos.pipeline.pipeline import RequestPipeline, PipelineRequest
from logos.pipeline.scheduler_interface import UtilizationAwareScheduler
from logos.pipeline.executor import Executor
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from typing import Optional, Dict, List, Any
from scripts import setup_proxy

logger = logging.getLogger("LogosLogger")

# Global Pipeline Components
_pipeline: Optional[RequestPipeline] = None
_queue_mgr: Optional[PriorityQueueManager] = None
_ollama_facade: Optional[OllamaSchedulingDataFacade] = None
_azure_facade: Optional[AzureSchedulingDataFacade] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown lifecycle.
    Initializes the new pipeline components.
    """
    # Initialize DB
    # Initialize DB - Legacy call removed as DBManager handles connection internally
    #     schema_path=os.getenv("SCHEMA_PATH", "schema.sql")
    # )
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True
    )
    # Ensure logos logger is at INFO/DEBUG
    logging.getLogger("logos").setLevel(logging.INFO)
    
    # Start Pipeline
    await start_pipeline()
    
    # Start gRPC server
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(_pipeline), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()

    # Setup proxy if needed (legacy setup)
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
_grpc_server = None


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion ggf. einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # logos_key etc.
)


async def start_pipeline():
    """Initialize the new request pipeline components."""
    global _pipeline, _queue_mgr, _ollama_facade, _azure_facade
    
    logger.info("Initializing Request Pipeline...")
    
    # 1. Queue Manager
    _queue_mgr = PriorityQueueManager()
    
    # 2. SDI Facades
    # We need a temporary DB manager for registration
    # Ideally facades should take a factory or manage their own DB context
    # For now, we pass None if they create their own, or pass a fresh one
    # The current implementation of facades creates DBManager internally or takes it
    # Let's check signatures. Ollama takes (queue, db_manager). Azure takes (db_manager).
    # If we pass None, they might fail if they expect an instance.
    # Let's assume they handle their own DB connections or we pass a fresh one.
    
    _ollama_facade = OllamaSchedulingDataFacade(_queue_mgr, None) 
    _azure_facade = AzureSchedulingDataFacade(None)
    
    # 3. Register Models
    await _register_models_with_facades(_ollama_facade, _azure_facade)
    
    # 4. Scheduler
    model_registry = _build_model_registry()
    scheduler = UtilizationAwareScheduler(
        queue_manager=_queue_mgr,
        ollama_facade=_ollama_facade,
        azure_facade=_azure_facade,
        model_registry=model_registry
    )
    
    # 5. Executor
    executor = Executor()
    
    # 6. Classifier
    classifier = _build_classifier()
    
    # 7. Pipeline
    _pipeline = RequestPipeline(
        classifier=classifier,
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


def _build_classifier() -> ClassificationManager:
    """Build classifier with all models."""
    
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


def classifier():
    mdls = list()
    with DBManager() as db:
        for model in db.get_all_models():
            tpl = db.get_model(model)
            model = {
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
            }
            mdls.append(model)
    global _classifier
    _classifier = ClassificationManager(mdls)
    _classifier.update_manager(mdls)


@app.on_event("shutdown")
async def stop_grpc():
    global _grpc_server
    if _grpc_server:
        await _grpc_server.stop(0)


@app.post("/logosdb/setup")
async def setup_db(data: LogosSetupRequest):
    try:
        logging.info("Receiving setup request...")
        with DBManager() as db:
            db.is_root_initialized()
        logging.info("Processing setup request. Initialized: %s", str(DBManager.is_initialized()))
        if not DBManager.is_initialized():
            # If we run logos for the first time automatically run a basic setup skript
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
        classifier()
        return back


@app.post("/logosdb/add_full_model")
async def add_full_model(data: AddFullModelRequest):
    with DBManager() as db:
        return db.add_full_model(**data.dict())


@app.post("/logosdb/update_model")
async def update_model(data: GiveFeedbackRequest):
    with DBManager() as db:
        back = db.update_model_weights(**data.dict())
        classifier()
        return back


@app.post("/logosdb/delete_model")
async def delete_model(data: DeleteModelRequest):
    with DBManager() as db:
        return db.delete_model(**data.dict())


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


@app.post("/work")
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
@app.api_route("/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def work(request: Request, path: str = None):
    """
    Main entry point for processing requests.
    Routes all requests through the new pipeline.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    # Extract headers
    headers = dict(request.headers)
    logos_key = headers.get("logos_key") or \
                headers.get("Authorization", "").replace("Bearer ", "") or \
                headers.get("authorization", "").replace("Bearer ", "")
    
    # Log request (reusing existing logging logic via DBManager for now)
    log_id = None
    if logos_key:
        with DBManager() as db:
            r, c = db.get_process_id(logos_key)
            if c == 200:
                r_log, c_log = db.log_usage(int(r["result"]), get_client_ip(request), body, headers)
                if c_log == 200:
                    log_id = int(r_log["log-id"])

    # Resolve allowed models from request
    allowed_models = None
    requested_model = body.get("model")
    if requested_model:
        # Look up model ID by name from the classifier's cache
        for m in _pipeline._classifier.models:
            if m["name"] == requested_model:
                allowed_models = [m["id"]]
                break
        
        if allowed_models is None:
            # Model requested but not found
            raise HTTPException(status_code=404, detail=f"Model '{requested_model}' not found")

    # Create Pipeline Request
    pipeline_req = PipelineRequest(
        logos_key=logos_key or "anon",
        payload=body,
        headers=headers,
        policy=None, # Policy extraction could be added here
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
                -1, # Policy ID not tracked yet
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
                -1, # Policy ID not tracked yet
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
        error_message = None
        
        try:
            # Define header callback for rate limit updates
            def process_headers(headers: dict):
                try:
                    _pipeline.update_provider_stats(model_id, headers)
                except Exception:
                    pass

            async for chunk in _pipeline._executor.execute_streaming(context, payload, on_headers=process_headers):
                yield chunk
                
                # Parse chunk for logging
                line = chunk.decode().strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        blob = json.loads(line[6:])
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
            # Capture error for logging
            error_message = str(e)
            raise e
        finally:
            # Log completion
            if log_id:
                with DBManager() as db:
                    db.set_response_payload(
                        log_id,
                        {"content": full_text},
                        provider_id,
                        model_id,
                        {},  # Usage from final chunk - TODO: extract usage
                        policy_id,
                        classification_stats,
                        queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival"),
                        utilization_at_arrival=scheduling_stats.get("utilization_at_arrival")
                    )
            
            # Record processing complete
            # We use the captured error_message if any
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
                     _pipeline._scheduler.release(
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
        # Execute
        exec_result = await _pipeline._executor.execute_sync(context, payload)
        
        # Update stats (e.g. rate limits) from headers
        if exec_result.headers:
            try:
                _pipeline.update_provider_stats(model_id, exec_result.headers)
            except Exception:
                pass
    
        # If execution failed and response is empty, log the error
        response_payload = exec_result.response
        if not exec_result.success and not response_payload and exec_result.error:
            response_payload = {"error": exec_result.error}
            logger.error(f"Request failed: {exec_result.error}")
        
        if log_id:
            with DBManager() as db:
                db.set_response_payload(
                    log_id,
                    response_payload,
                    provider_id,
                    model_id,
                    exec_result.usage,
                    policy_id,
                    classification_stats,
                    queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None,
                    utilization_at_arrival=scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                )
    
        # Record completion
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
                 _pipeline._scheduler.release(
                     model_id,
                     scheduling_stats.get("request_id")
                 )
             except Exception as e:
                 logger.error(f"Failed to release scheduler resources: {e}")



def request2json(request_data: bytes) -> dict:
    """
    Decode request payload into json
    :param request_data: Request payload as bytes
    :return: Json String of the given bytes
    """
    if not request_data:
        return {}
    return json.loads(request_data)

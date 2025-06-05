import json
import traceback

import grpc
from fastapi import FastAPI, Request

from grpclocal import model_pb2_grpc
from grpclocal.grpc_server import LogosServicer
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import *
from logos.responses import get_streaming_response, get_standard_response, get_client_ip, request_setup, \
    proxy_behaviour, resource_behaviour
from logos.scheduling.scheduling_fcfs import FCFSScheduler
from logos.scheduling.scheduling_manager import SchedulingManager
from scripts import setup_proxy

from scripts.setup_proxy import setup

app = FastAPI(docs_url="/docs", openapi_url="/openapi.json")
_grpc_server = None

@app.on_event("startup")
async def start_grpc():
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()


@app.on_event("shutdown")
async def stop_grpc():
    global _grpc_server
    if _grpc_server:
        await _grpc_server.stop(0)
    sm = SchedulingManager(FCFSScheduler())
    sm.stop()


@app.post("/logosdb/setup")
async def setup_db(data: LogosSetupRequest):
    try:
        print("Recieving setup request...", flush=True)
        with DBManager() as db:
            db.is_root_initialized()
        print("Processing setup request. Initialized: " + str(DBManager.is_initialized()), flush=True)
        if not DBManager.is_initialized():
            # If we run logos for the first time automatically run a basic setup skript
            lk = setup(**data.dict())
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
        return db.add_model(**data.dict())


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


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def logos_service(path: str, request: Request):
    """
    Dynamic proxy for Endpoints
    :param path: Path to Endpoint
    :param request: Request
    :return: The response from Endpoints
    """
    headers = dict(request.headers)
    # Read request
    data = await request.body()
    json_data = request2json(data)
    # logos-API-check
    logos_key = headers["logos_key"] if "logos_key" in headers else (
        headers["Authorization"].replace("Bearer ", "") if "Authorization" in headers else "")

    # Check if Logos is used as proxy or resource
    models = request_setup(headers, logos_key)
    if not models:
        with DBManager() as db:
            # Get available providers for this key
            providers = db.get_providers(logos_key)
        # Find most suitable provider
        out = proxy_behaviour(headers, providers, path)
        if isinstance(out[0], dict) and "error" in out[0]:
            return out
        proxy_headers, forward_url, provider_id = out
        model_id, model_name = None, None
    else:
        out = resource_behaviour(logos_key, headers, json_data, models)
        if isinstance(out[0], dict) and "error" in out[0]:
            return out
        proxy_headers, forward_url, model_id, model_name, provider_id = out

    with DBManager() as db:
        process_id = db.get_process_id(logos_key)
        if db.log(process_id):
            request_id = db.log_request(process_id, get_client_ip(request), json_data, provider_id, model_id, headers)
        else:
            request_id = None
    # Forward Request
    # Try multiple requesting methods. Start with streaming
    try:
        print("Sending Streaming Request")
        json_data["stream"] = True
        return get_streaming_response(forward_url, proxy_headers, json_data, model_name, request_id, provider_id, model_id)
    except:
        traceback.print_exc()
    # Fall back to naive request method
    try:
        print("Falling back to Standard Request")
        json_data["stream"] = False
        return await get_standard_response(forward_url, proxy_headers, json_data, model_name, request_id, provider_id, model_id)
    except:
        traceback.print_exc()
    return {"error": "provider not reachable"}, 500


def request2json(request_data: bytes) -> dict:
    """
    Decode request payload into json
    :param request_data: Request payload as bytes
    :return: Json String of the given bytes
    """
    if not request_data:
        return {}
    string = request_data.decode('utf8').replace("'", '"')
    return json.loads(string)

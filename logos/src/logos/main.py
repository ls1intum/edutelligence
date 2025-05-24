import json
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
from requests import JSONDecodeError

from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import *

from scripts.setup_proxy import setup

app = FastAPI()


@app.post("/logosdb/setup")
async def setup_db(data: LogosSetupRequest):
    try:
        if not DBManager.is_initialized():
            # If we run logos for the first time automatically run a basic setup skript
            lk = setup(**data.dict())
            return {"logos-key": lk}
        return {"error": "Database already initialized"}
    except Exception as e:
        return {"error": f"{str(e)}"}, 401


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


def request_setup(headers: dict, path: str, llm_info: dict):
    try:
        key = headers["logos_key"] if "logos_key" in headers else (
            headers["Authorization"].replace("Bearer ", "") if "Authorization" in headers else "")
        with DBManager() as db:
            # For now, we only redirect to saved models in the db if
            # it is present in the db and no further info is provided
            model_id = None
            api_key = llm_info["api_key"]
            base_url: str = llm_info["base_url"]
            provider = llm_info["provider_name"]
            # Check if model is in db
            # Check for api-key
            model_api_id = db.get_model_from_api(key, llm_info["api_id"])
            model_provider_id = db.get_model_from_provider(key, llm_info["provider_id"])
            if model_api_id is None and model_provider_id is None or "proxy" in headers:
                # Model not in the database, change to normal proxy
                if provider == "azure":
                    if "deployment_name" not in headers or headers["deployment_name"] == "":
                        return {"error": "Missing deployment name in header"}, 401
                    if "api_version" not in headers or headers["api_version"] == "":
                        return {"error": "Missing api version in header"}, 401
                    deployment_name = headers["deployment_name"]
                    api_version = headers["api_version"]

                    forward_url = (
                        f"{base_url}/{deployment_name}/{path}"
                        f"?api-version={api_version}"
                    )
                    forward_url = forward_url[:8] + forward_url[8:].replace("//", "/")

                    proxy_headers = {
                        "api-key": headers["api_key"],
                        "Content-Type": "application/json"
                    }
                else:
                    proxy_headers = {
                        "Authorization": f"Bearer {headers["api_key"]}",
                        "Content-Type": "application/json"
                    }
                    forward_url = f"{base_url}/{path}"
            else:
                model_id = model_api_id if model_api_id is not None else model_provider_id
                model_data = db.get_model(model_id)
                endpoint = model_data["endpoint"]
                if not base_url.endswith("/") and not endpoint.startswith("/"):
                    forward_url = f"{base_url}/{endpoint}"
                elif base_url.endswith("/") and endpoint.startswith("/"):
                    forward_url = f"{base_url[:-1]}/{endpoint[1:]}"
                else:
                    forward_url = f"{base_url}{endpoint}"

                # forward_url = forward_url.replace("///", "/")
                auth_name = llm_info["auth_name"]
                auth_format = llm_info["auth_format"].format(api_key)
                proxy_headers = {
                    auth_name: auth_format,
                    "Content-Type": "application/json"
                }
        return proxy_headers, forward_url, model_id
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401


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
    key = headers["logos_key"] if "logos_key" in headers else (
        headers["Authorization"].replace("Bearer ", "") if "Authorization" in headers else "")
    # Get an api key for a llm. This is the starting point for classification later
    with DBManager() as db:
        llm_info = db.fetch_llm_key(key)
        if llm_info is None:
            return {"error": "Key not found"}, 401
        tmp = request_setup(headers, path, llm_info)
        if isinstance(tmp[0], dict) and "error" in tmp[0]:
            return tmp
        proxy_headers, forward_url, model_id = tmp
        if db.log(llm_info["process_id"]):
            request_id = db.log_request(llm_info["process_id"], get_client_ip(request), json_data, llm_info["provider_id"], model_id, headers)
        else:
            request_id = None
    # Forward Request
    """async with httpx.AsyncClient() as client:
        response = await client.request(
            method="POST",
            url=forward_url,
            json=json_data,
            headers=proxy_headers,
            timeout=30,
        )

    try:
        return response.json()
    except JSONDecodeError:
        return response.text
    client = GRPCModelClient(target_host=forward_url)

    def token_generator():
        for chunk in client.generate_stream(payload=json_data, deployment_name=headers["deployment_name"],
                                            api_key=headers["api_key"], api_version=headers["api_version"],
                                            authorization=f"Bearer {headers["api_key"]}"):
            yield chunk

    return StreamingResponse(token_generator(), media_type="text/plain")
    json_data["stream"] = True

    async def stream_response():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(method="POST", url=forward_url, headers=proxy_headers, json=json_data) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(stream_response(), media_type="application/json")
    """

    headers["authorization"] = f"Bearer {headers["api_key"]}"
    # Try multiple requesting methods. Start with streaming
    try:
        print("Sending Streaming Request")
        json_data["stream"] = True

        async def stream_response():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(method="POST", url=forward_url, headers=proxy_headers,
                                         json=json_data, timeout=30) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk

        return StreamingResponse(stream_response(), media_type="application/json")
    except:
        traceback.print_exc()
    # Fall back to naive request method
    try:
        print("Falling back to Standard Request")
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method="POST",
                url=forward_url,
                json=json_data,
                headers=proxy_headers,
                timeout=30,
            )

        try:
            return response.json()
        except JSONDecodeError:
            return response.text
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


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host

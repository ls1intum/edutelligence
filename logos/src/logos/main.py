import json
from json import JSONDecodeError
from fastapi import FastAPI, Request
import httpx

from logos.dbmanager import DBManager
from logos.dbrequest import *

app = FastAPI()


@app.post("/logosdb/setup")
async def setup_db():
    try:
        with DBManager() as db:
            return db.setup()
    except Exception as e:
        return {"error": f"{str(e)}"}, 401


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


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def logos_service(path: str, request: Request):
    """
    Dynamic proxy for Endpoints
    :param path: Path to Endpoint
    :param request: Request
    :return: The response from Endpoints
    """
    # Read request
    data = await request.body()
    json_data = request2json(data)
    # logos-API-check
    if "Authorization" not in request.headers and "logos_key" not in request.headers:
        return {"error": "Missing Authorization Header"}, 401
    try:
        key = request.headers["logos_key"] if "logos_key" in request.headers else (
            request.headers["Authorization"].replace("Bearer ", ""))
        with DBManager() as db:
            # Get an api key for a llm. This is the starting point for classification later
            llm_info = db.fetch_llm_key(key)
            if llm_info is None:
                return {"error": "Key not found"}, 401
            # For now, we only redirect to saved models in the db if
            # it is present in the db and no further info is provided
            api_key = llm_info["api_key"]
            base_url: str = llm_info["base_url"]
            provider = llm_info["provider_name"]
            # Check if model is in db
            # Check for api-key
            model_api_id = db.get_model_from_api(key, llm_info["api_id"])
            model_provider_id = db.get_model_from_provider(key, llm_info["provider_id"])
            if model_api_id is None and model_provider_id is None or "proxy" in request.headers:
                # Model not in the database, change to normal proxy
                if provider == "azure":
                    if "deployment_name" not in request.headers:
                        return {"error": "Missing deployment name in header"}, 401
                    if "api_version" not in request.headers:
                        return {"error": "Missing api version in header"}, 401
                    deployment_name = request.headers["deployment_name"]
                    api_version = request.headers["api_version"]

                    forward_url = (
                        f"{base_url}/{deployment_name}/{path}"
                        f"?api-version={api_version}"
                    )

                    headers = {
                        "api-key": request.headers["api_key"],
                        "Content-Type": "application/json"
                    }
                else:
                    headers = {
                        "Authorization": f"Bearer {request.headers["api_key"]}",
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
                headers = {
                    auth_name: auth_format,
                    "Content-Type": "application/json"
                }
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401
    # Forward Request
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method="POST",
            url=forward_url,
            json=json_data,
            headers=headers,
            timeout=30,
        )

    try:
        return response.json()
    except JSONDecodeError:
        return response.text


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

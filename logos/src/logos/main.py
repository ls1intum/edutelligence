import json
from json import JSONDecodeError
from fastapi import FastAPI, Request
import httpx

from logos.constants import *
from logos.config import KeyManager


config = KeyManager()


app = FastAPI()


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def openai_proxy(path: str, request: Request):
    """
    Dynamic proxy for openai-Endpoints
    :param path: Path to Endpoint
    :param request: Request
    :return: The response from OpenAI Endpoints
    """
    # Read request
    data = await request.body()
    json = request2json(data)
    # logos-API-check
    if "Authorization" not in request.headers:
        return {"error": "Missing Authorization Header"}, 401
    try:
        key = request.headers["Authorization"].replace("Bearer ", "")
        if "provider" not in request.headers:
            provider = "openai"
        else:
            provider = request.headers["provider"]
        # Check if key is an openai-Key (just for proxy purposes)
        if not key.startswith("sk-"):
            key = config.get_llm_key(key, provider)
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401

    if provider == "azure":
        deployment_name = request.headers["deployment_name"]
        api_version = request.headers["api_version"]

        forward_url = (
            f"{AZURE_API_BASE}/{deployment_name}/{path}"
            f"?api-version={api_version}"
        )

        headers = {
            "api-key": key,
            "Content-Type": "application/json"
        }
    else:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        forward_url = f"{OPENAI_API_BASE}/{path}"

    # Forward Request
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method="POST",
            url=forward_url,
            json=json,
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

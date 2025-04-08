import json
from json import JSONDecodeError

from fastapi import FastAPI, Request
import httpx

from logos.constants import *
from logos.config import KeyManager


config = KeyManager("logos.local.yml")


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
    # logos-API with password
    pwd = json.get("password") if "password" in json else None
    usr = json.get("user") if "user" in json else "default"
    try:
        key = config.get_key(user=usr, model=json.get("model") if "model" in json else "", pwd=pwd)
    except PermissionError as e:
        return {"error": str(e)}
    if key is None:
        return {"error": "Invalid user or model provided"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    # Forward Request
    async with httpx.AsyncClient() as client:
        openai_url = f"{OPENAI_API_BASE}/{path}"
        response = await client.request(
            method="POST",
            url=openai_url,
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

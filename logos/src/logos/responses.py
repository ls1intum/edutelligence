import json
from typing import Union

import tiktoken
from fastapi.responses import StreamingResponse
import httpx
import grpc
from requests import JSONDecodeError, Response
from starlette.requests import Request

from logos.dbutils.dbmanager import DBManager


def get_streaming_response(forward_url, proxy_headers, json_data, model_name, request_id, provider_id, model_id):
    json_data = json_data.copy()
    json_data["stream"] = True

    full_text = ""
    response: Union[None, dict] = None

    async def streamer():
        nonlocal full_text, response
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", forward_url, headers=proxy_headers, json=json_data) as resp:
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        if raw_line.startswith("data: "):
                            payload = raw_line.removeprefix("data: ").strip()
                            if payload == "[DONE]":
                                break
                            try:
                                blob = json.loads(payload)
                                if "choices" in blob and blob["choices"] and "delta" in blob["choices"][0] and "content" in blob["choices"][0]["delta"]:
                                    content = blob["choices"][0]["delta"]["content"]
                                    if content:
                                        full_text += content
                                    response = blob
                            except:
                                pass
                        yield (raw_line + "\n").encode()
        finally:
            after_streaming()

    # Logging-Funktion
    def after_streaming():
        if request_id is None:
            return
        try:
            enc = tiktoken.encoding_for_model(model_name)
        except:
            enc = tiktoken.get_encoding("cl100k_base")
        completion_tokens = len(enc.encode(full_text))
        prompt_tokens = len(enc.encode(json_data.get("messages", [{}])[0].get("content", "")))
        total_tokens = prompt_tokens + completion_tokens
        with DBManager() as db:
            nonlocal response
            if response is not None:
                response["choices"][0]["delta"]["content"] = full_text
            else:
                response = full_text
            db.log_usage(request_id, response, prompt_tokens, completion_tokens, total_tokens, provider_id, model_id)

    # Response + call_on_close
    return StreamingResponse(streamer(), media_type="application/json")


async def get_standard_response(forward_url, proxy_headers, json_data, model_name, request_id, provider_id, model_id):
    async with httpx.AsyncClient() as client:
        response: Response = await client.request(
            method="POST",
            url=forward_url,
            json=json_data,
            headers=proxy_headers,
            timeout=30,
        )
    try:
        response: dict = response.json()
    except JSONDecodeError:
        response: dict = {"error": response.text}
    if request_id is not None:
        try:
            enc = tiktoken.encoding_for_model(model_name)
        except:
            enc = tiktoken.get_encoding("cl100k_base")
        if "choices" in response and response["choices"] and "delta" in response["choices"][0] and "content" in response["choices"][0][
            "delta"]:
            completion_tokens = len(enc.encode(response["choices"][0]["delta"]["content"]))
            prompt_tokens = len(enc.encode(json_data.get("messages", [{}])[0].get("content", "")))
            total_tokens = prompt_tokens + completion_tokens
        else:
            completion_tokens = prompt_tokens = total_tokens = 0
        with DBManager() as db:
            db.log_usage(request_id, response, prompt_tokens, completion_tokens, total_tokens, provider_id, model_id)
    return response


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def get_client_ip_address_from_context(context: grpc.ServicerContext) -> str:
    peer = context.peer()
    if peer.startswith("ipv4:"):
        return peer.split(":")[1]
    return peer


def request_setup(headers: dict, path: str, llm_info: dict):
    try:
        key = headers["logos_key"] if "logos_key" in headers else (
            headers["Authorization"].replace("Bearer ", "") if "Authorization" in headers else "")
        with DBManager() as db:
            # For now, we only redirect to saved models in the db if
            # it is present in the db and no further info is provided
            model_id = None
            model_name = None
            api_key = llm_info["api_key"]
            base_url: str = llm_info["base_url"]
            provider = llm_info["provider_name"]
            # Check if model is in db
            # Check for api-key
            model_api_id = db.get_model_from_api(key, llm_info["api_id"])
            model_provider_id = db.get_model_from_provider(key, llm_info["provider_id"])
            if model_api_id is None and model_provider_id is None or "proxy" in headers:
                # Model not in the database, change to normal proxy
                if "azure" in provider.lower():
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
                        "Authorization": headers["Authorization"],
                        "Content-Type": "application/json"
                    }
                    forward_url = f"{base_url}/{path}"
            else:
                model_id = model_api_id if model_api_id is not None else model_provider_id
                model_data = db.get_model(model_id)
                model_name = model_data["name"]
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
        return proxy_headers, forward_url, model_id, model_name
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401

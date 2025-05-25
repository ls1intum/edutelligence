import json
from typing import Union

import tiktoken
from fastapi.responses import StreamingResponse
import httpx
from requests import JSONDecodeError, Response

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
        # log_usage(self, request_id: int, response_body: str, prompt_tokens: int, completion_tokens: int,
        #                   total_tokens: int, provider_id: int, model_id: int)

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

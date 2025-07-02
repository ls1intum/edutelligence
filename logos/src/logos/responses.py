import datetime
import json
import time
from typing import Union

import tiktoken
from fastapi.responses import StreamingResponse
import httpx
import grpc
import yaml
from requests import JSONDecodeError, Response
from starlette.requests import Request

from logos.classification.classification_manager import ClassificationManager
from logos.classification.proxy_policy import ProxyPolicy
from logos.dbutils.dbmanager import DBManager
from logos.scheduling.scheduling_fcfs import FCFSScheduler
from logos.scheduling.scheduling_manager import SchedulingManager


def get_streaming_response(forward_url, proxy_headers, json_data, log_id, provider_id, model_id):
    json_data = json_data.copy()
    json_data["stream"] = True
    json_data["stream_options"] = {"include_usage": True}

    full_text = ""
    response: Union[None, dict] = None
    first_response = None
    ttft = None

    async def streamer():
        nonlocal full_text, response, first_response, ttft
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", forward_url, headers=proxy_headers, json=json_data) as resp:
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        if raw_line.startswith("data: "):
                            if ttft is None:
                                ttft = datetime.datetime.now(datetime.timezone.utc)
                                with DBManager() as db:
                                    db.set_time_at_first_token(log_id)
                            payload = raw_line.removeprefix("data: ").strip()
                            if payload == "[DONE]":
                                break
                            try:
                                blob = json.loads(payload)
                                response = blob
                                if "choices" in blob and blob["choices"] and "delta" in blob["choices"][0] and "content" in blob["choices"][0]["delta"]:
                                    content = blob["choices"][0]["delta"]["content"]
                                    if first_response is None:
                                        first_response = blob
                                    if content:
                                        full_text += content
                            except:
                                pass
                        yield (raw_line + "\n").encode()
        finally:
            after_streaming()

    # Logging-Funktion
    def after_streaming():
        if model_id is not None:
            sm = SchedulingManager(FCFSScheduler())
            sm.set_free(model_id)
        if log_id is None:
            return

        with DBManager() as db:
            nonlocal response, ttft, first_response
            if first_response is not None:
                usage = response["usage"] if response is not None else dict()
                first_response["choices"][0]["delta"]["content"] = full_text
                usage_tokens = dict()
                for name in usage:
                    if "tokens_details" in name:
                        continue
                    usage_tokens[name] = usage[name]
                if "prompt_tokens_details" in usage:
                    for name in usage["prompt_tokens_details"]:
                        usage_tokens["prompt_" + name] = usage["prompt_tokens_details"][name]
                if "completion_tokens_details" in usage:
                    for name in usage["completion_tokens_details"]:
                        usage_tokens["completion_" + name] = usage["completion_tokens_details"][name]
                first_response["usage"] = response["usage"]
            else:
                response = {"content": full_text}
                first_response = {"content": full_text}
                usage_tokens = dict()
            if ttft is None:
                db.set_time_at_first_token(log_id)
            db.set_response_payload(log_id, first_response, provider_id, model_id, usage_tokens)

    # Response + call_on_close
    return StreamingResponse(streamer(), media_type="application/json")


async def get_standard_response(forward_url, proxy_headers, json_data, log_id, provider_id, model_id):
    try:
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
        if log_id is not None:
            usage = response["usage"] if response is not None else dict()
            usage_tokens = dict()
            for name in usage:
                if "tokens_details" in name:
                    continue
                usage_tokens[name] = usage[name]
            if "prompt_tokens_details" in usage:
                for name in usage["prompt_tokens_details"]:
                    usage_tokens[name] = usage["prompt_tokens_details"][name]
            if "completion_tokens_details" in usage:
                for name in usage["completion_tokens_details"]:
                    usage_tokens[name] = usage["completion_tokens_details"][name]
            with DBManager() as db:
                db.set_time_at_first_token(log_id)
                db.set_response_timestamp(log_id)
                db.set_response_payload(log_id, response, provider_id, model_id, usage_tokens)
        return response
    finally:
        if model_id is not None:
            sm = SchedulingManager(FCFSScheduler())
            sm.set_free(model_id)


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


def parse_provider_config(name):
    with open(f"./logos/config/config-{name}.yaml") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError:
            return {
                'provider': 'openwebui',
                'forward_url': '{base_url}/{path}',
                'required_headers': ['Authorization'],
                'auth': {'header': 'Authorization', 'format': '{Authorization}'}
            }


def proxy_behaviour(headers, providers, path):
    """
    Adopt normal proxy behaviour. If we have multiple suitable providers, check the one that fits to the headers.
    """
    proxy_headers = None
    forward_url = None
    for provider in providers:
        with DBManager() as db:
            provider_info = db.get_provider(provider)

        if "azure" in provider_info["name"].lower():
            config = parse_provider_config("azure")
        elif "openwebui" in provider_info["name"].lower():
            config = parse_provider_config("openwebui")
        elif "openai" in provider_info["name"].lower() and "Authorization" in headers and "sk-" in headers["Authorization"]:
            config = parse_provider_config("openai")
        else:
            continue

        req_headers = config["required_headers"]
        check = True
        for req_header in req_headers:
            if req_header not in headers:
                check = False
                break
        if not check:
            continue
        req_headers = {i: headers[i] for i in req_headers}
        req_headers["base_url"] = provider_info["base_url"]
        req_headers["path"] = path

        forward_url = config["forward_url"].format(**req_headers)
        forward_url = forward_url[:8] + forward_url[8:].replace("//", "/")

        proxy_headers = {
            config["auth"]["header"]: config["auth"]["format"].format(**req_headers),
            "Content-Type": "application/json"
        }
    if proxy_headers is None:
        return {"error": "Could not identify suitable provider. Please check you header and registered provider names"}, 500
    return proxy_headers, forward_url, int(provider_info["id"])


def resource_behaviour(logos_key, headers, data, models):
    # The interesting part: Classification and scheduling
    # First, retrieve our used policy. If no one is given, use default ProxyPolicy
    mdls = list()
    with DBManager() as db:
        for tpl in db.get_models_info(logos_key):
            if tpl[0] not in models:
                continue
            model = {
                "id": tpl[0],
                "name": tpl[1],
                "endpoint": tpl[2],
                "api_id": tpl[3],
                "weight_privacy": tpl[4],
                "weight_latency": tpl[5],
                "weight_accuracy": tpl[6],
                "weight_cost": tpl[7],
                "weight_quality": tpl[8],
                "tags": tpl[9],
                "parallel": tpl[10],
                "description": tpl[11],
                "classification_weight": 1,
            }
            mdls.append(model)
    select = ClassificationManager(mdls)
    if "policy" in headers:
        with DBManager() as db:
            policy = db.get_policy(logos_key, headers["policy"])
    else:
        policy = ProxyPolicy()

    # Extract our prompt (needed for classification)
    prompt = extract_prompt(data)
    models = select.classify(prompt, policy)
    sm = SchedulingManager(FCFSScheduler())
    sm.run()
    tid = sm.add_request(data, models)

    # Wait for this task to be executed
    while not sm.is_finished(tid):
        pass

    out = sm.get_result()
    if out is None:
        return {"error": f"No executable found for task {tid}"}, 500
    # Get final model-ID
    model_id = out.get_best_model_id()
    if model_id is None:
        return {"error": f"No executable found for task {tid}"}, 500
    with DBManager() as db:
        model = db.get_model(model_id)
        provider = db.get_provider_to_model(model_id)
        api_key = db.get_key_to_model_provider(model_id, provider["id"])
    if api_key is None:
        return {"error": f"No api_key found for task {tid} with model {model_id} and provider {provider["name"]}"}, 500
    model_name = model["name"]
    forward_url = merge_url(provider["base_url"], model["endpoint"])
    auth_name = provider["auth_name"]
    auth_format = provider["auth_format"].format(api_key)
    proxy_headers = {
        auth_name: auth_format,
        "Content-Type": "application/json"
    }
    return proxy_headers, forward_url, model_id, model_name, int(provider["id"])


def merge_url(base_url, endpoint):
    if not base_url.endswith("/") and not endpoint.startswith("/"):
        forward_url = f"{base_url}/{endpoint}"
    elif base_url.endswith("/") and endpoint.startswith("/"):
        forward_url = f"{base_url[:-1]}/{endpoint[1:]}"
    else:
        forward_url = f"{base_url}{endpoint}"
    return forward_url


def request_setup(headers: dict, logos_key: str):
    try:
        # Check if Logos is used as proxy or resource
        with DBManager() as db:
            # Get available models for this key
            if "use_profile" in headers:
                models = db.get_models_by_profile(logos_key, int(headers["use_profile"]))
            else:
                models = db.get_models_with_key(logos_key)
        if not models or "proxy" in headers:
            return list()
        else:
            with DBManager() as db:
                return [i for i in [db.get_model(i) for i in models] if i is not None]
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401


def extract_prompt(json_data: dict) -> str:
    if "input_payload" in json_data:
        if "messages" in json_data["input_payload"]:
            if json_data["input_payload"]["messages"]:
                if "content" in json_data["input_payload"]["messages"][0]:
                    return json_data["input_payload"]["messages"][0]["content"]
    return ""

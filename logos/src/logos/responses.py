import datetime
import json
import logging
import time
from typing import Union, List, Dict, Any

from fastapi.responses import StreamingResponse
import httpx
import grpc
import yaml
from requests import JSONDecodeError, Response
from starlette.requests import Request

from logos.classification.classification_manager import ClassificationManager
from logos.classification.proxy_policy import ProxyPolicy
from logos.dbutils.dbmanager import DBManager
from logos.model_string_parser import parse_model_string
from logos.scheduling.scheduling_fcfs import FCFSScheduler
from logos.scheduling.scheduling_manager import SchedulingManager


def get_streaming_response(forward_url, proxy_headers, json_data, log_id, provider_id, model_id, policy_id, classified):
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
                                if "choices" in blob and blob["choices"] and "delta" in blob["choices"][
                                    0] and "content" in blob["choices"][0]["delta"]:
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
                    if name in {"approximate_total", "eval_count", "eval_duration", "load_duration",
                                "prompt_eval_count", "prompt_eval_duration", "prompt_token/s", "response_token/s",
                                "total_duration"} or "/s" in name:
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
            db.set_response_payload(log_id, first_response, provider_id, model_id, usage_tokens, policy_id, classified)

    # Response + call_on_close
    return StreamingResponse(streamer(), media_type="application/json")


async def get_standard_response(forward_url, proxy_headers, json_data, log_id, provider_id, model_id, policy_id,
                                classified):
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
                if name in {"approximate_total", "eval_count", "eval_duration", "load_duration", "prompt_eval_count",
                            "prompt_eval_duration", "prompt_token/s", "response_token/s",
                            "total_duration"} or "/s" in name:
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
                db.set_response_payload(log_id, response, provider_id, model_id, usage_tokens, policy_id, classified)
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
        elif "openai" in provider_info["name"].lower() and "Authorization" in headers and "sk-" in headers[
            "Authorization"]:
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
        return {
            "error": "Could not identify suitable provider. Please check you header and registered provider names"}, 500
    return proxy_headers, forward_url, int(provider_info["id"])


def resource_behaviour(logos_key, headers, data, models):
    # The interesting part: Classification and scheduling
    # Retrieve our used policy. If no one is given, use default ProxyPolicy
    if "policy" in headers:
        with DBManager() as db:
            policy = db.get_policy(logos_key, int(headers["policy"]))
    else:
        policy = ProxyPolicy()
    # Get Model name (in case the application already defined which model to use)
    mdl = extract_model(data)
    if mdl.startswith("logos-v"):
        try:
            model_string_dto = parse_model_string(mdl)
            p = model_string_dto.policy
            if not p["default"]:
                for key in p:
                    if key == "default":
                        continue
                    if key == "privacy":
                        policy["threshold_privacy"] = p[key]
                    # TODO: Add other policy settings
        except Exception as e:
            logging.warning("Could not parse model string: %s", e)
    if isinstance(policy, dict) and "error" in policy:
        return {"error": "Could not identify suitable policy."}, 500
    tmp_mdls = list()
    with DBManager() as db:
        for model in db.get_all_models():
            tpl = db.get_model(model)
            model = {
                "id": tpl["id"],
                "name": tpl["name"],
                "parallel": tpl["parallel"],
            }
            tmp_mdls.append(model)
    found = False
    for model in tmp_mdls:
        if mdl == model["name"]:
            found = (model["id"], 1024, policy["priority"], model["parallel"])
            break
    if not found:
        select = ClassificationManager(list())
        # Extract our prompt (needed for classification)
        prompts = extract_prompt(data)
        user_prompt, system_prompt = prompts["user"], prompts["system"]
        start = time.time()
        mdls = select.classify(user_prompt, policy, allowed=models, system=system_prompt)
        end = time.time()
        if not mdls:
            return {"error": "Could not identify suitable model."}, 500
        logging.info(f"Model weights after classification: {[(i, j) for i, j, _, _ in mdls]}")
        # Get IDs of classified models
        classified = {i for i, _, _, _ in mdls}
        classified = {
            "classification_data": [
                {
                    "latency_weight": model["classification_weight"].weights["policy"][0] if len(
                        model["classification_weight"].weights["policy"]) > 0 else -1,
                    "accuracy_weight": model["classification_weight"].weights["policy"][1] if len(
                        model["classification_weight"].weights["policy"]) > 1 else -1,
                    "quality_weight": model["classification_weight"].weights["policy"][2] if len(
                        model["classification_weight"].weights["policy"]) > 2 else -1,
                    "token_weight": model["classification_weight"].weights["token"][0] if len(
                        model["classification_weight"].weights["token"]) > 0 else -1,
                    "laura_weight": model["classification_weight"].weights["ai"][0] if len(
                        model["classification_weight"].weights["ai"]) > 0 else -1,
                    "laura_factor": model["classification_weight"].LAURA_WEIGHT,
                    "token_factor": model["classification_weight"].TOKEN_WEIGHT,
                    "combined_weight": model["classification_weight"].get_weight(),
                    "model_id": model["id"],
                }
                for model in select.filtered
                if model["id"] in classified
            ],
            "classification_time": end - start,
        }
    else:
        logging.info(f"Skipping classification, using model {mdl}")
        mdls = [found]
        classified = {
            "classification_data": [
                {
                    "latency_weight": -1,
                    "accuracy_weight": -1,
                    "quality_weight": -1,
                    "token_weight": -1,
                    "laura_weight": -1,
                    "laura_factor": -1,
                    "token_factor": -1,
                    "combined_weight": -1,
                    "model_id": found[0],
                }
            ],
            "classification_time": 0,
        }
    sm = SchedulingManager(FCFSScheduler())
    sm.run()
    tid = sm.add_request(data, mdls)

    # Wait for this task to be executed
    while not sm.is_finished(tid):
        pass

    out = sm.get_result()
    if out is None:
        return {"error": f"No executable found for task {tid}"}, 500
    model_id = -1
    while out.models:
        # Get final model-ID
        model_id = out.get_best_model_id()
        if model_id is None:
            logging.error(f"No executable found for task {tid}")
            out.models = out.models[1:]
            continue
        with DBManager() as db:
            model = db.get_model(model_id)
            provider = db.get_provider_to_model(model_id)
            api_key = db.get_key_to_model_provider(model_id, provider["id"])
        if api_key is None:
            logging.error(f"No api_key found for task {tid} with model {model_id} and provider {provider["name"]}")
            out.models = out.models[1:]
            continue
        break
    if not out.models:
        return {"error": f"No model found for task {tid}"}, 500
    model_name = model["name"]
    logging.info(f"Forwarding to model {model_name} after classification")
    forward_url = merge_url(provider["base_url"], model["endpoint"])
    auth_name = provider["auth_name"]
    auth_format = provider["auth_format"].format(api_key)
    proxy_headers = {
        auth_name: auth_format,
        "Content-Type": "application/json"
    }
    return proxy_headers, forward_url, model_id, model_name, int(provider["id"]), provider["name"], policy[
        "id"], classified


def merge_url(base_url, endpoint):
    if endpoint.startswith("http"):
        return endpoint
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
            # Return ids of all available models
            logging.info(f"Found models {models} for classification")
            return models
    except PermissionError as e:
        return {"error": str(e)}, 401
    except ValueError as e:
        return {"error": str(e)}, 401


def extract_model(json_data: dict) -> str:
    if "model" in json_data:
        return json_data["model"]
    # gRPC
    elif "input_payload" in json_data and "model" in json_data["input_payload"]:
        return json_data["input_payload"]["model"]
    return ""


def _extract_text_from_content(content: Union[str, List[Dict[str, Any]]]) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "text":
                continue
            txt = part.get("text")
            if isinstance(txt, str):
                parts.append(txt)
        return "\n".join(parts)
    return ""


def extract_prompt(json_data: Dict[str, Any]) -> Dict[str, str]:
    messages: List[Dict[str, Any]] = []
    if "input_payload" in json_data and "messages" in json_data["input_payload"]:
        messages = json_data["input_payload"]["messages"]
    elif "messages" in json_data:
        messages = json_data["messages"]

    last_by_role: Dict[str, Dict[str, Any]] = {}

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = str(msg.get("role", "")).lower()
        if role not in {"system", "user"}:
            continue

        last_by_role[role] = msg

    system_text = ""
    user_text = ""

    if "system" in last_by_role:
        system_text = _extract_text_from_content(last_by_role["system"].get("content", ""))

    if "user" in last_by_role:
        user_text = _extract_text_from_content(last_by_role["user"].get("content", ""))

    return {"system": system_text, "user": user_text}

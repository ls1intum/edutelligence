import json, traceback, httpx, grpc, datetime

from grpclocal import model_pb2, model_pb2_grpc
from logos.dbutils.dbmanager import DBManager
from logos.responses import request_setup, get_client_ip_address_from_context, proxy_behaviour, resource_behaviour, \
    get_client_ip
from logos.scheduling.scheduling_fcfs import FCFSScheduler
from logos.scheduling.scheduling_manager import SchedulingManager


class LogosServicer(model_pb2_grpc.LogosServicer):
    async def Generate(self, request, context):
        # Metadata (aka Header in REST)
        meta = dict()
        for k, v in request.metadata.items():
            meta[k] = v
        if "logos_key" not in meta:
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Missing logos_key")
            return
        path = request.path

        # Parse JSON body
        try:
            data = json.loads(request.payload)
        except json.JSONDecodeError:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Invalid JSON payload")
            return

        with DBManager() as db:
            r, c = db.get_process_id(meta["logos_key"])
            if c != 200:
                print("Error while logging a request: ", r)
                usage_id = None
            else:
                r, c = db.log_usage(int(r["result"]), get_client_ip_address_from_context(request), data, meta)
                if c != 200:
                    usage_id = None
                else:
                    usage_id = int(r["log-id"])

        models = request_setup(meta, meta["logos_key"])
        if not models:
            with DBManager() as db:
                # Get available providers for this key
                providers = db.get_providers(meta["logos_key"])
            # Find most suitable provider
            out = proxy_behaviour(meta, providers, path)
            if isinstance(out[0], dict) and "error" in out[0]:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(f"Upstream error: {out[0]["error"]}")
                return
            proxy_headers, forward_url, provider_id = out
            model_id, model_name = None, None
            policy_id = -1
            classified = dict()
        else:
            out = resource_behaviour(meta["logos_key"], meta, data, models)
            if isinstance(out[0], dict) and "error" in out[0]:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details(f"Upstream error: {out[0]["error"]}")
                return
            proxy_headers, forward_url, model_id, model_name, provider_id, _, policy_id, classified = out

        # Standard request setup

        with DBManager() as db:
            if usage_id is not None:
                db.set_forward_timestamp(usage_id)

        full_text = ""
        data["stream"] = True
        data["stream_options"] = {"include_usage": True}
        last_blob = None
        ttft = None
        try:
            # Try streaming first, fall back to standard response on failure
            for _ in range(2):
                try:
                    async with httpx.AsyncClient(timeout=None) as client:
                        async with client.stream("POST", forward_url, headers=proxy_headers, json=data) as resp:
                            async for raw_line in resp.aiter_lines():
                                if not raw_line:
                                    continue

                                # Parse Data-Chunk
                                if raw_line.startswith("data: "):
                                    payload = raw_line.removeprefix("data: ").strip()
                                    if ttft is None and usage_id is not None:
                                        ttft = datetime.datetime.now(datetime.timezone.utc)
                                        with DBManager() as db:
                                            db.set_time_at_first_token(usage_id)
                                    if payload == "[DONE]":
                                        break
                                    try:
                                        blob = json.loads(payload)
                                        choices = blob.get("choices", [])
                                        if choices and "delta" in choices[0]:
                                            content = choices[0]["delta"].get("content")
                                            if content:
                                                full_text += content
                                        last_blob = blob
                                    except Exception:
                                        pass

                                # Yield to gRPC-Client
                                yield model_pb2.GenerateResponse(chunk=(raw_line + "\n").encode())
                    break
                except:
                    traceback.print_exc()
                    print("Falling back to Standard Request")
                    data["stream"] = False
        except Exception as e:
            traceback.print_exc()
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(f"Upstream error: {e}")
            return

        if ttft is None and usage_id is not None:
            db.set_time_at_first_token(usage_id)

        # Usage-Logging
        if usage_id is not None:
            try:
                response_for_log = last_blob
                if response_for_log:
                    response_for_log["choices"][0]["delta"]["content"] = full_text

                    usage = response_for_log["usage"] if response_for_log is not None else dict()
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
                    response_for_log["usage"] = response_for_log["usage"]
                else:
                    response_for_log = {"full_text": full_text}
                    usage_tokens = dict()

                with DBManager() as db:
                    db.set_response_payload(usage_id, response_for_log, provider_id, model_id, usage_tokens, policy_id, classified)
            except Exception:
                traceback.print_exc()

        if model_id is not None:
            sm = SchedulingManager(FCFSScheduler())
            sm.set_free(model_id)

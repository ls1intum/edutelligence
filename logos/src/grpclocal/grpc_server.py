import json, traceback, httpx, grpc

import tiktoken

from grpclocal import model_pb2, model_pb2_grpc
from logos.dbutils.dbmanager import DBManager
from logos.responses import request_setup, get_client_ip_address_from_context


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
            llm_info = db.fetch_llm_key(meta["logos_key"])
            if llm_info is None:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("Key not found")
                return

        # Standard request setup
        try:
            tmp = request_setup(meta, path, llm_info)
            if isinstance(tmp[0], dict) and "error" in tmp[0]:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(tmp[0]["error"])
                return
            proxy_headers, forward_url, model_id, model_name = tmp
        except Exception as e:
            traceback.print_exc()
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(f"Routing error: {e}")
            return
        if db.log(llm_info["process_id"]):
            request_id = db.log_request(llm_info["process_id"], get_client_ip_address_from_context(context), data, llm_info["provider_id"], model_id, meta)
        else:
            request_id = None
        full_text = ""
        data["stream"] = True
        last_blob = None
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

        # Usage-Logging
        if request_id is not None:
            try:
                try:
                    enc = tiktoken.encoding_for_model(model_name)
                except:
                    enc = tiktoken.get_encoding("cl100k_base")

                prompt_tokens = len(enc.encode(data.get("messages", [{}])[0].get("content", "")))
                completion_tokens = len(enc.encode(full_text))
                total_tokens = prompt_tokens + completion_tokens

                response_for_log = last_blob
                if response_for_log:
                    response_for_log["choices"][0]["delta"]["content"] = full_text
                else:
                    response_for_log = {"full_text": full_text}

                with DBManager() as db:
                    db.log_usage(
                        request_id=request_id,
                        response_body=response_for_log,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        provider_id=llm_info["provider_id"],
                        model_id=model_id,
                    )
            except Exception:
                traceback.print_exc()

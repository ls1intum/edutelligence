import json
import traceback
import grpc
import logging

from grpclocal import model_pb2, model_pb2_grpc
from logos.pipeline.pipeline import RequestPipeline, PipelineRequest


class LogosServicer(model_pb2_grpc.LogosServicer):
    def __init__(self, pipeline: RequestPipeline):
        self.pipeline = pipeline

    async def Generate(self, request, context):
        # Metadata (aka Header in REST)
        meta = dict()
        for k, v in request.metadata.items():
            meta[k] = v
        
        if "logos_key" not in meta:
            context.set_code(grpc.StatusCode.UNAUTHENTICATED)
            context.set_details("Missing logos_key")
            return

        # Parse JSON body
        try:
            data = json.loads(request.payload)
        except json.JSONDecodeError:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Invalid JSON payload")
            return

        # Create Pipeline Request
        # We treat gRPC requests as streaming by default if not specified
        if "stream" not in data:
            data["stream"] = True

        pipeline_req = PipelineRequest(
            payload=data,
            headers=meta,
            logos_key=meta.get("logos_key", "unknown")
        )

        try:
            # Process request through pipeline
            result = await self.pipeline.process(pipeline_req)
            
            if not result.success:
                await context.abort(grpc.StatusCode.UNAVAILABLE, result.error or "Pipeline processing failed")
                return

            # Determine streaming mode
            is_streaming = data.get("stream", False)
            
            # Execute
            if is_streaming:
                async for chunk in self.pipeline._executor.execute_ressource_streaming(result.execution_context, data):
                    yield model_pb2.GenerationResponse(text=chunk.decode())
            else:
                exec_result = await self.pipeline._executor.execute_ressource_sync(result.execution_context, data)
                if not exec_result.success:
                    await context.abort(grpc.StatusCode.INTERNAL, exec_result.error or "Execution failed")
                yield model_pb2.GenerationResponse(text=json.dumps(exec_result.response))
                
            self.pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status="SUCCESS"
            )

        except Exception as e:
            # Try to record error if we have a request ID (might be None if pipeline failed early)
            # But here we are inside the try block where result might not be defined if process() failed
            # However, if process() fails, we abort above. So if we are here, result is defined.
            # Wait, if process() raises exception, result is undefined.
            # We should wrap the whole thing or check locals.
            
            # Simplified: just log error and abort
            logging.error(f"gRPC Execution Error: {e}")
            traceback.print_exc()
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

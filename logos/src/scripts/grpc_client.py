
import grpc
from grpclocal import model_pb2, model_pb2_grpc

def run_grpc_client(headers, path, payload):
    """
    Creates a gRPC-Client that can communicate with Logos Server via gRPC.
    """
    channel = grpc.insecure_channel("0.0.0.0:50051")
    stub = model_pb2_grpc.LogosStub(channel)

    request = model_pb2.GenerateRequest(
        path=path,
        metadata=headers,
        payload=payload
    )

    try:
        for response in stub.Generate(request):
            yield response.chunk.decode()
    except grpc.RpcError as e:
        yield f"\nRPC error: {e.code()}: {e.details()}"

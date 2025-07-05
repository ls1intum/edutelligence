
import grpc
from grpclocal import model_pb2, model_pb2_grpc

def run_grpc_client(headers: dict, path: str, payload: str):
    """
    Creates a gRPC-Client that can communicate with Logos Server via gRPC.
    :param headers: Headers as sent in REST
    :param path: Path to the Logos-Endpoint, e.g. "chat/completions"
    :param payload: Payload as sent in REST, provided as string
    """
    channel = grpc.secure_channel("logos.ase.cit.tum.de:50051", grpc.ssl_channel_credentials())
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

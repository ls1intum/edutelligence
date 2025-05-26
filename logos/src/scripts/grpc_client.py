
import grpc
from grpclocal import model_pb2, model_pb2_grpc

def run_grpc_client(headers, path, payload):
    # gRPC-Channel zur Logos-Instanz
    channel = grpc.insecure_channel("0.0.0.0:50051")  # passe Port ggf. an
    stub = model_pb2_grpc.LogosStub(channel)

    # JSON-String mit Chat-Komplettierungsdaten (z. B. OpenAI-kompatibel)

    request = model_pb2.GenerateRequest(
        path=path,
        metadata=headers,
        payload=payload
    )

    print("==> Streaming Antwort:")
    try:
        for response in stub.Generate(request):
            print(response.chunk.decode(), end="")
    except grpc.RpcError as e:
        print(f"\nRPC error: {e.code()}: {e.details()}")

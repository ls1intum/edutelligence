import grpc, json
from src.grpclocal import model_pb2, model_pb2_grpc


class GRPCModelClient:
    def __init__(self, target_host: str):
        self.channel = grpc.secure_channel(target_host, grpc.ssl_channel_credentials())
        self.stub = model_pb2_grpc.ModelServiceStub(self.channel)

    def generate_stream(self, payload: dict, deployment_name: str, api_key: str, api_version: str, authorization: str):
        req = model_pb2.GenerateRequest(json=json.dumps(payload))
        metadata = (
            ("api-key", api_key),
            ("deployment_name", deployment_name),
            ("api_version", api_version),
            ("authorization", authorization),
        )
        for resp in self.stub.Generate(req, metadata=metadata):
            yield resp.text_chunk

import grpc
from src.grpclocal import model_pb2, model_pb2_grpc


class GRPCModelClient:
    def __init__(self, target_host: str):
        self.channel = grpc.insecure_channel(target_host)
        self.stub = model_pb2_grpc.ModelServiceStub(self.channel)

    def generate_stream(self, json: dict, deployment_name: str, api_key: str, api_version: str, authorization: str):
        req = model_pb2.GenerateRequest(json=json)
        metadata = (
            ("api_key", api_key),
            ("deployment_name", deployment_name),
            ("api_version", api_version),
            ("authorization", authorization),
        )
        for resp in self.stub.Generate(req, metadata=metadata):
            yield resp.text_chunk

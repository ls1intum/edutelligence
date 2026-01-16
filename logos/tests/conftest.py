"""
Global test configuration:
- Ensure `src/` is on sys.path
- Stub heavy/optional modules that aren't needed for unit/integration tests
  (sentence_transformers, grpclocal/protobuf stubs) to keep tests fully offline.
"""

import sys
import pathlib
import types

# Add src to path
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Stub optional heavy dependencies
sys.modules.setdefault(
    "sentence_transformers",
    types.SimpleNamespace(SentenceTransformer=lambda *a, **k: None, util=None),
)

# Minimal grpclocal/protobuf stubs to avoid binary/runtime deps in tests
grpclocal_pkg = types.ModuleType("grpclocal")
grpclocal_model_pb2 = types.ModuleType("grpclocal.model_pb2")
grpclocal_model_pb2_grpc = types.ModuleType("grpclocal.model_pb2_grpc")
grpclocal_grpc_server = types.ModuleType("grpclocal.grpc_server")

class DummyServicer:
    def __init__(self, *a, **k):
        pass

grpclocal_grpc_server.LogosServicer = DummyServicer

grpclocal_pkg.model_pb2 = grpclocal_model_pb2
grpclocal_pkg.model_pb2_grpc = grpclocal_model_pb2_grpc
grpclocal_pkg.grpc_server = grpclocal_grpc_server

sys.modules["grpclocal"] = grpclocal_pkg
sys.modules["grpclocal.model_pb2"] = grpclocal_model_pb2
sys.modules["grpclocal.model_pb2_grpc"] = grpclocal_model_pb2_grpc
sys.modules["grpclocal.grpc_server"] = grpclocal_grpc_server

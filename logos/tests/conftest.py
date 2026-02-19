"""
Global test configuration for Logos.

Ensures ``src/`` is on *sys.path* and installs lightweight stubs for heavy or
optional dependencies (gRPC binaries, ML frameworks, database drivers, …) so
that **unit tests can be collected and executed without installing every
production dependency**.

The stubs use ``sys.modules.setdefault`` — when the real package *is*
installed (e.g. inside the Docker image) it takes precedence automatically.
"""

import sys
import pathlib
import types

# ---------------------------------------------------------------------------
# Python path
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------------------
# Ignore manual / credential-dependent test scripts during collection
# ---------------------------------------------------------------------------

collect_ignore_glob = [
    "network_test.py",           # Reads API keys from a local file
    "config_test.py",            # Requires a running server
    "langchainTest.py",          # Manual LangChain experiment
    "performance/*",             # Performance benchmarks (not unit tests)
    "support/*",                 # Support / helper scripts
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_noop = lambda *a, **k: None  # noqa: E731


def _make_module(name: str, attrs: dict | None = None) -> types.ModuleType:
    """Create a stub module, set it in *sys.modules* (if absent), and return it."""
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


def _make_submodule(parent: types.ModuleType, child_name: str,
                    attrs: dict | None = None) -> types.ModuleType:
    """Create *parent.child_name* and register it in *sys.modules*."""
    fqn = f"{parent.__name__}.{child_name}"
    child = _make_module(fqn, attrs)
    setattr(parent, child_name, child)
    return child


# ---------------------------------------------------------------------------
# 1. sentence_transformers  (ML embeddings — pulls PyTorch)
# ---------------------------------------------------------------------------

sys.modules.setdefault(
    "sentence_transformers",
    types.SimpleNamespace(SentenceTransformer=_noop, util=None),
)

# ---------------------------------------------------------------------------
# 2. grpclocal  (generated protobuf / gRPC stubs)
# ---------------------------------------------------------------------------


class _DummyServicer:
    """Stand-in for the generated ``LogosServicer``."""
    def __init__(self, *a, **k):
        pass


grpclocal_pkg = _make_module("grpclocal")
_make_submodule(grpclocal_pkg, "model_pb2")
grpclocal_pb2_grpc = _make_submodule(
    grpclocal_pkg, "model_pb2_grpc",
    {"add_LogosServicer_to_server": _noop},
)
_make_submodule(grpclocal_pkg, "grpc_server", {"LogosServicer": _DummyServicer})

# ---------------------------------------------------------------------------
# 3. grpc / grpcio  (C-extension — not always installable)
# ---------------------------------------------------------------------------

grpc_mod = _make_module("grpc", {
    "insecure_channel": _noop,
    "server": _noop,
    "StatusCode": types.SimpleNamespace(OK=0),
})
_make_submodule(grpc_mod, "aio", {"server": _noop})

# ---------------------------------------------------------------------------
# 4. requests  (HTTP client used by SDI providers)
# ---------------------------------------------------------------------------

_requests_mod = _make_module("requests", {
    "get": _noop,
    "post": _noop,
    "put": _noop,
    "delete": _noop,
    "Session": type("Session", (), {"get": _noop, "post": _noop}),
    "Response": type("Response", (), {
        "status_code": 200, "text": "", "json": _noop, "content": b"",
    }),
})
_make_submodule(_requests_mod, "exceptions", {
    "RequestException": type("RequestException", (Exception,), {}),
    "ConnectionError": type("ConnectionError", (Exception,), {}),
    "Timeout": type("Timeout", (Exception,), {}),
})

# ---------------------------------------------------------------------------
# 5. yaml / PyYAML
# ---------------------------------------------------------------------------

_make_module("yaml", {
    "safe_load": _noop,
    "dump": _noop,
    "YAMLError": type("YAMLError", (Exception,), {}),
})

# ---------------------------------------------------------------------------
# 6. torch  (PyTorch — huge, not needed for unit tests)
# ---------------------------------------------------------------------------

_torch = _make_module("torch", {
    "device": _noop,
    "Tensor": type("Tensor", (), {}),
    "stack": _noop,
    "no_grad": lambda fn=None: (lambda f: f) if fn is None else fn,
})
_torch_cuda = _make_submodule(_torch, "cuda", {"is_available": lambda: False})

# ---------------------------------------------------------------------------
# 7. SQLAlchemy  (ORM — dbmodules.py defines models at import time)
# ---------------------------------------------------------------------------


class _DummyMeta:
    """Minimal ``MetaData`` stand-in."""
    create_all = _noop
    drop_all = _noop
    tables = {}


class _DummyBase:
    """Return value of ``declarative_base()`` — must be sub-classable."""
    metadata = _DummyMeta()

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        # Mimic SQLAlchemy's __tablename__ / __table_args__ handling
        cls.__table__ = types.SimpleNamespace(columns=[])


sa = _make_module("sqlalchemy", {
    # Column types / constraints  (all callable, return None — fine for class bodies)
    "Column": _noop, "Integer": _noop, "String": _noop, "Text": _noop,
    "Float": _noop, "Boolean": _noop, "Numeric": _noop, "Enum": _noop,
    "JSON": _noop, "TIMESTAMP": _noop, "DateTime": _noop,
    "ForeignKey": _noop, "CheckConstraint": _noop,
    # DDL / query helpers
    "Table": _noop, "MetaData": _DummyMeta, "create_engine": _noop,
    "text": _noop, "func": types.SimpleNamespace(count=_noop, sum=_noop),
    "bindparam": _noop, "inspect": _noop,
})
sa_exc = _make_submodule(sa, "exc", {
    "ProgrammingError": type("ProgrammingError", (Exception,), {}),
    "IntegrityError": type("IntegrityError", (Exception,), {}),
    "OperationalError": type("OperationalError", (Exception,), {}),
})
sa_orm = _make_submodule(sa, "orm", {
    "sessionmaker": _noop,
    "relationship": _noop,
    "Session": type("Session", (), {}),
})
sa_ext = _make_submodule(sa, "ext")
_make_submodule(sa_ext, "declarative", {"declarative_base": lambda **kw: _DummyBase})

# ---------------------------------------------------------------------------
# 8. psycopg2  (PostgreSQL driver — loaded by SQLAlchemy at runtime)
# ---------------------------------------------------------------------------

_make_module("psycopg2")
_make_module("psycopg2.extras")

# ---------------------------------------------------------------------------
# 9. dateutil  (python-dateutil — date parsing)
# ---------------------------------------------------------------------------

_du = _make_module("dateutil")
_make_submodule(_du, "parser", {"isoparse": _noop, "parse": _noop})

# ---------------------------------------------------------------------------
# 10. aiohttp  (async HTTP for Ollama monitoring)
# ---------------------------------------------------------------------------

_aiohttp = _make_module("aiohttp", {
    "ClientSession": _noop,
    "ClientTimeout": _noop,
    "TCPConnector": _noop,
    "ClientError": type("ClientError", (Exception,), {}),
})

# ---------------------------------------------------------------------------
# 11. matplotlib  (plotting — only used in test_model_data.py)
# ---------------------------------------------------------------------------

_mpl = _make_module("matplotlib")
_make_submodule(_mpl, "pyplot", {
    "figure": _noop, "show": _noop, "plot": _noop,
    "xlabel": _noop, "ylabel": _noop, "title": _noop,
    "legend": _noop, "savefig": _noop, "close": _noop,
    "bar": _noop, "subplot": _noop, "tight_layout": _noop,
})

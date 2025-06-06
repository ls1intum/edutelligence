# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc
import warnings

from . import hyperion_pb2 as hyperion__pb2

GRPC_GENERATED_VERSION = "1.71.0"
GRPC_VERSION = grpc.__version__
_version_not_supported = False

try:
    from grpc._utilities import first_version_is_lower

    _version_not_supported = first_version_is_lower(
        GRPC_VERSION, GRPC_GENERATED_VERSION
    )
except ImportError:
    _version_not_supported = True

if _version_not_supported:
    raise RuntimeError(
        f"The grpc package installed is at version {GRPC_VERSION},"
        + f" but the generated code in hyperion_pb2_grpc.py depends on"
        + f" grpcio>={GRPC_GENERATED_VERSION}."
        + f" Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}"
        + f" or downgrade your generated code using grpcio-tools<={GRPC_VERSION}."
    )


class HealthStub(object):
    """Health check service"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.Ping = channel.unary_unary(
            "/hyperion.Health/Ping",
            request_serializer=hyperion__pb2.PingRequest.SerializeToString,
            response_deserializer=hyperion__pb2.PingResponse.FromString,
            _registered_method=True,
        )


class HealthServicer(object):
    """Health check service"""

    def Ping(self, request, context):
        """Check if the server is running"""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_HealthServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "Ping": grpc.unary_unary_rpc_method_handler(
            servicer.Ping,
            request_deserializer=hyperion__pb2.PingRequest.FromString,
            response_serializer=hyperion__pb2.PingResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.Health", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers("hyperion.Health", rpc_method_handlers)


# This class is part of an EXPERIMENTAL API.
class Health(object):
    """Health check service"""

    @staticmethod
    def Ping(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/hyperion.Health/Ping",
            hyperion__pb2.PingRequest.SerializeToString,
            hyperion__pb2.PingResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )


class DefineBoundaryConditionStub(object):
    """Exercise Creation Step 1: Define Boundary Conditions"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class DefineBoundaryConditionServicer(object):
    """Exercise Creation Step 1: Define Boundary Conditions"""


def add_DefineBoundaryConditionServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.DefineBoundaryCondition", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.DefineBoundaryCondition", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class DefineBoundaryCondition(object):
    """Exercise Creation Step 1: Define Boundary Conditions"""


class DraftProblemStatementStub(object):
    """Exercise Creation Step 2: Create Draft Problem Statement"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class DraftProblemStatementServicer(object):
    """Exercise Creation Step 2: Create Draft Problem Statement"""


def add_DraftProblemStatementServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.DraftProblemStatement", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.DraftProblemStatement", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class DraftProblemStatement(object):
    """Exercise Creation Step 2: Create Draft Problem Statement"""


class CreateSolutionRepositoryStub(object):
    """Exercise Creation Step 3: Create Solution Repository"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class CreateSolutionRepositoryServicer(object):
    """Exercise Creation Step 3: Create Solution Repository"""


def add_CreateSolutionRepositoryServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.CreateSolutionRepository", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.CreateSolutionRepository", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class CreateSolutionRepository(object):
    """Exercise Creation Step 3: Create Solution Repository"""


class CreateTemplateRepositoryStub(object):
    """Exercise Creation Step 4: Create Template Repository"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class CreateTemplateRepositoryServicer(object):
    """Exercise Creation Step 4: Create Template Repository"""


def add_CreateTemplateRepositoryServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.CreateTemplateRepository", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.CreateTemplateRepository", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class CreateTemplateRepository(object):
    """Exercise Creation Step 4: Create Template Repository"""


class CreateTestRepositoryStub(object):
    """Exercise Creation Step 5: Create Test Repository"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class CreateTestRepositoryServicer(object):
    """Exercise Creation Step 5: Create Test Repository"""


def add_CreateTestRepositoryServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.CreateTestRepository", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.CreateTestRepository", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class CreateTestRepository(object):
    """Exercise Creation Step 5: Create Test Repository"""


class FinalizeProblemStatementStub(object):
    """Exercise Creation Step 6: Finalize Problem Statement"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class FinalizeProblemStatementServicer(object):
    """Exercise Creation Step 6: Finalize Problem Statement"""


def add_FinalizeProblemStatementServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.FinalizeProblemStatement", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.FinalizeProblemStatement", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class FinalizeProblemStatement(object):
    """Exercise Creation Step 6: Finalize Problem Statement"""


class ConfigureGradingStub(object):
    """Exercise Creation Step 7: Configure Grading"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """


class ConfigureGradingServicer(object):
    """Exercise Creation Step 7: Configure Grading"""


def add_ConfigureGradingServicer_to_server(servicer, server):
    rpc_method_handlers = {}
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.ConfigureGrading", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.ConfigureGrading", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class ConfigureGrading(object):
    """Exercise Creation Step 7: Configure Grading"""


class VerifyConfigurationStub(object):
    """Exercise Creation Step 8: Verify Configuration"""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.CheckInconsistencies = channel.unary_unary(
            "/hyperion.VerifyConfiguration/CheckInconsistencies",
            request_serializer=hyperion__pb2.InconsistencyCheckRequest.SerializeToString,
            response_deserializer=hyperion__pb2.InconsistencyCheckResponse.FromString,
            _registered_method=True,
        )


class VerifyConfigurationServicer(object):
    """Exercise Creation Step 8: Verify Configuration"""

    def CheckInconsistencies(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_VerifyConfigurationServicer_to_server(servicer, server):
    rpc_method_handlers = {
        "CheckInconsistencies": grpc.unary_unary_rpc_method_handler(
            servicer.CheckInconsistencies,
            request_deserializer=hyperion__pb2.InconsistencyCheckRequest.FromString,
            response_serializer=hyperion__pb2.InconsistencyCheckResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "hyperion.VerifyConfiguration", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        "hyperion.VerifyConfiguration", rpc_method_handlers
    )


# This class is part of an EXPERIMENTAL API.
class VerifyConfiguration(object):
    """Exercise Creation Step 8: Verify Configuration"""

    @staticmethod
    def CheckInconsistencies(
        request,
        target,
        options=(),
        channel_credentials=None,
        call_credentials=None,
        insecure=False,
        compression=None,
        wait_for_ready=None,
        timeout=None,
        metadata=None,
    ):
        return grpc.experimental.unary_unary(
            request,
            target,
            "/hyperion.VerifyConfiguration/CheckInconsistencies",
            hyperion__pb2.InconsistencyCheckRequest.SerializeToString,
            hyperion__pb2.InconsistencyCheckResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True,
        )

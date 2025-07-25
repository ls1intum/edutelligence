# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc
import warnings

from grpclocal import model_pb2 as model__pb2

GRPC_GENERATED_VERSION = '1.71.0'
GRPC_VERSION = grpc.__version__
_version_not_supported = False

try:
    from grpc._utilities import first_version_is_lower
    _version_not_supported = first_version_is_lower(GRPC_VERSION, GRPC_GENERATED_VERSION)
except ImportError:
    _version_not_supported = True

if _version_not_supported:
    raise RuntimeError(
        f'The grpc package installed is at version {GRPC_VERSION},'
        + f' but the generated code in model_pb2_grpc.py depends on'
        + f' grpcio>={GRPC_GENERATED_VERSION}.'
        + f' Please upgrade your grpc module to grpcio>={GRPC_GENERATED_VERSION}'
        + f' or downgrade your generated code using grpcio-tools<={GRPC_VERSION}.'
    )


class LogosStub(object):
    """One gRPC service for every incoming client
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.Generate = channel.unary_stream(
                '/logos.grpc.Logos/Generate',
                request_serializer=model__pb2.GenerateRequest.SerializeToString,
                response_deserializer=model__pb2.GenerateResponse.FromString,
                _registered_method=True)


class LogosServicer(object):
    """One gRPC service for every incoming client
    """

    def Generate(self, request, context):
        """Streams back chunks of the LLM response
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_LogosServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'Generate': grpc.unary_stream_rpc_method_handler(
                    servicer.Generate,
                    request_deserializer=model__pb2.GenerateRequest.FromString,
                    response_serializer=model__pb2.GenerateResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'logos.grpc.Logos', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('logos.grpc.Logos', rpc_method_handlers)


 # This class is part of an EXPERIMENTAL API.
class Logos(object):
    """One gRPC service for every incoming client
    """

    @staticmethod
    def Generate(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_stream(
            request,
            target,
            '/logos.grpc.Logos/Generate',
            model__pb2.GenerateRequest.SerializeToString,
            model__pb2.GenerateResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)

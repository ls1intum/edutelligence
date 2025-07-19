import logging
import os
from concurrent import futures

import grpc

from nebula.gateway.handlers.faq_handler import FAQServiceHandler
from nebula.grpc_stubs import faq_pb2_grpc

logger = logging.getLogger("nebula.gateway")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Read port from environment variable (default: 50051)
GATEWAY_SERVICE_PORT = os.getenv("GATEWAY_SERVICE_PORT", "50051")
server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))


def serve():
    # Register FAQ handler
    faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQServiceHandler(), server)
    logger.info("Registered gRPC handler for FAQ rewriting")
    server.add_insecure_port(f"[::]:{GATEWAY_SERVICE_PORT}")
    logger.info(f"gRPC server running on port {GATEWAY_SERVICE_PORT}")
    server.start()
    server.wait_for_termination()


def stop():
    server.stop(grace=None)  # grace=None = sofort

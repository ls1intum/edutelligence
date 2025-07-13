import logging
import os
from concurrent import futures

import grpc

from nebula.faq.services.rewriter_servicer import FAQRewriterService
from nebula.grpc_stubs import faq_pb2_grpc

logger = logging.getLogger("nebula.faq")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Load gRPC port from environment variable (default: 50052)
FAQ_SERVICE_PORT = os.getenv("FAQ_SERVICE_PORT", "50052")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    # Register FAQ-related gRPC services
    faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQRewriterService(), server)

    server.add_insecure_port(f"[::]:{FAQ_SERVICE_PORT}")
    logger.info(f"FAQ gRPC server running on port {FAQ_SERVICE_PORT}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()

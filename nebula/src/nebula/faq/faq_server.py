import logging
import grpc
from concurrent import futures

from nebula.grpc_stubs import faq_pb2_grpc
from nebula.faq.rewriter_servicer import FAQRewriterService
# Future imports for other FAQ-related gRPC services can go here

logger = logging.getLogger("nebula.faq.server")
logging.basicConfig(level=logging.INFO)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    # Register FAQ-related gRPC services
    faq_pb2_grpc.add_FAQServiceServicer_to_server(FAQRewriterService(), server)
    # Example: add_FAQSyncServiceServicer_to_server(...)
    server.add_insecure_port("[::]:50052")
    logging.info("🚀 FAQ gRPC server running on port 50052")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
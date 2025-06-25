import logging
import grpc
from grpc import ServicerContext
from nebula.grpc_stubs import faq_pb2, faq_pb2_grpc

logger = logging.getLogger("nebula.gateway.grpc.faq")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


class FAQServiceHandler(faq_pb2_grpc.FAQServiceServicer):
    def RewriteFAQ(self, request: faq_pb2.FaqRewritingRequest, context: ServicerContext) -> faq_pb2.FaqRewritingResponse:
        logger.info("📥 RewriteFAQ received – forwarding to downstream gRPC service")

        try:
            # Connect to the downstream gRPC service (e.g., faq running in another container)
            with grpc.insecure_channel("faq:50052") as channel:
                stub = faq_pb2_grpc.FAQServiceStub(channel)

                # Forward the received gRPC request as-is
                response = stub.RewriteFAQ(request)

                logger.info("✅ Received response from downstream service")
                return response

        except Exception as e:
            # Log and return internal server error in case of failure
            logger.error("❌ Failed to forward request: %s", str(e))
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return faq_pb2.FaqRewritingResponse(result="Internal error while forwarding request")

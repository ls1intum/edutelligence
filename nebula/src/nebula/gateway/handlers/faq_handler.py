import logging
import os
import grpc
from grpc import ServicerContext
from nebula.grpc_stubs import faq_pb2, faq_pb2_grpc

logger = logging.getLogger("nebula.gateway.grpc.faq")

# Load downstream service configuration from environment variables
FAQ_SERVICE_NAME = os.getenv("FAQ_SERVICE_NAME", "faq")
FAQ_SERVICE_PORT = os.getenv("FAQ_SERVICE_PORT", "50052")
FAQ_SERVICE_ADDRESS = f"{FAQ_SERVICE_NAME}:{FAQ_SERVICE_PORT}"


class FAQServiceHandler(faq_pb2_grpc.FAQServiceServicer):
    def RewriteFAQ(self, request: faq_pb2.FaqRewritingRequest, context: ServicerContext) -> faq_pb2.FaqRewritingResponse:
        logger.info(f"Received RewriteFAQ request – forwarding to downstream service at {FAQ_SERVICE_ADDRESS}")

        try:
            with grpc.insecure_channel(FAQ_SERVICE_ADDRESS) as channel:
                stub = faq_pb2_grpc.FAQServiceStub(channel)
                response = stub.RewriteFAQ(request)
                logger.info("Successfully received response from downstream service")
                return response

        except Exception as e:
            logger.error("Failed to forward request: %s", str(e))
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return faq_pb2.FaqRewritingResponse(result="Internal error while forwarding request")

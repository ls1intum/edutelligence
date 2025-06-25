import logging
from grpc import ServicerContext
from nebula.grpc_stubs import faq_pb2, faq_pb2_grpc

logger = logging.getLogger("nebula.faq.rewriter")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

class FAQRewriterService(faq_pb2_grpc.FAQServiceServicer):
    def RewriteFAQ(self, request: faq_pb2.FaqRewritingRequest, context: ServicerContext) -> faq_pb2.FaqRewritingResponse:
        logger.info(f"Received RewriteFAQ request with input text: '{request.input_text}' and {len(request.faqs)} FAQ(s)")

        # Placeholder for actual rewriting logic (e.g., LLM or embedding-based lookup)
        rewritten_text = f"Rewritten (mocked) for: '{request.input_text}' using {len(request.faqs)} FAQ(s)."

        return faq_pb2.FaqRewritingResponse(result=rewritten_text)

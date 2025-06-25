import logging
from grpc import ServicerContext
from nebula.grpc_stubs import faq_pb2, faq_pb2_grpc

logger = logging.getLogger("nebula.faq.rewriter")

class FAQRewriterService(faq_pb2_grpc.FAQServiceServicer):
    def RewriteFAQ(self, request: faq_pb2.FaqRewritingRequest, context: ServicerContext) -> faq_pb2.FaqRewritingRequest:
        logger.info("🔁 FAQRewriterService: received RewriteFAQ request")

        # Here you can apply real rewriting logic later (e.g., LLM or embedding-based lookup)
        rewritten_text = f"Rewritten (mocked) for: '{request.input_text}' using {len(request.faqs)} FAQ(s)."

        return faq_pb2.FaqRewritingResponse(result=rewritten_text)

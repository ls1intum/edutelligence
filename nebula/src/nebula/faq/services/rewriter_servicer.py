import logging
from grpc import ServicerContext
from nebula.grpc_stubs import faq_pb2, faq_pb2_grpc
from nebula.llm.openai_client import get_openai_client
from nebula.faq.prompts.rewrite_faq_prompt import system_prompt_faq_rewriting


logger = logging.getLogger("nebula.faq.rewriter")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

class FAQRewriterService(faq_pb2_grpc.FAQServiceServicer):
    def RewriteFAQ(self, request: faq_pb2.FaqRewritingRequest, context: ServicerContext) -> faq_pb2.FaqRewritingResponse:
        logger.info(f"Received RewriteFAQ request with input text: '{request.input_text}' and {len(request.faqs)} FAQ(s)")

        try:
            client, deployment = get_openai_client("azure-gpt-4-omni")

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt_faq_rewriting.format(rewritten_text=request.input_text),
                    },
                ],
            )

            rewritten_text = response.choices[0].message.content.strip()

        except Exception as e:
            logger.error("Failed to rewrite FAQ: %s", str(e), exc_info=True)
            context.set_details("Error while contacting the LLM")
            return faq_pb2.FaqRewritingResponse(result="")

        return faq_pb2.FaqRewritingResponse(result=rewritten_text)

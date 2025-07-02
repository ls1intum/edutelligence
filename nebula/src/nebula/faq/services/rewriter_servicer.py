import logging
import time
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
        logger.info("Received RewriteFAQ request with input text: '%s' and %d FAQ(s)", request.input_text, len(request.faqs))

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

    def RewriteFAQStream(self, request: faq_pb2.FaqRewritingRequest, context: ServicerContext):
        logger.info(f"🔁 Streaming RewriteFAQ request with {len(request.faqs)} FAQ(s)")

        total_steps = 5
        for step in range(total_steps):
            progress = int((step / total_steps) * 100)
            yield faq_pb2.FaqRewriteStatusUpdate(
                status_message=f"Processing... ({progress}%)",
                progress_percent=progress,
                done=False
            )
            time.sleep(2)  # ⏱️ Simulate work

        try:
            client, deployment = get_openai_client("azure-gpt-4-omni")

            yield faq_pb2.FaqRewriteStatusUpdate(
                status_message="Sending input to LLM...",
                progress_percent=90,
                done=False
            )

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
            logger.error("❌ Failed during rewriting: %s", str(e), exc_info=True)
            context.set_details("Error while contacting the LLM")
            context.set_code(13)  # INTERNAL error code
            return  # Ends the stream on error

        yield faq_pb2.FaqRewriteStatusUpdate(
            status_message="✅ Rewriting complete.",
            progress_percent=100,
            done=True,
            final_result=rewritten_text
        )

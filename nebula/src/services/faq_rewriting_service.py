import json
import logging
from typing import List, Optional
from grpc_stub import faq_pb2, faq_pb2_grpc


def format_faqs_for_openai(faqs: Optional[List[faq_pb2.FAQ]]) -> str:
    faqs = faqs or []
    print(f"Formatting {len(faqs)} FAQs for OpenAI")
    return json.dumps([
        {
            "question_title": faq.question_title,
            "question_answer": faq.question_answer
        } for faq in faqs
    ], indent=2)


class FaqRewritingService(faq_pb2_grpc.FAQServiceServicer):
    """
    Implements the FAQService gRPC interface.
    """

    def ProcessInput(
        self,
        request: faq_pb2.FaqRewritingRequest,
        context
    ) -> faq_pb2.FaqRewritingResponse:
        """
        Handles incoming gRPC requests to rewrite FAQ text.
        """
        # 1. Extrahiere Input
        input_text = request.input_text
        faqs = request.faqs

        logging.info(f"Received request with input: {input_text} and {len(faqs)} FAQs")
        logging.debug(f"FAQs: {faqs}")
        # 2. Formatiere FAQs (z.B. für späteren LLM-Aufruf)
        formatted_faqs = format_faqs_for_openai(faqs)

        # 3. Placeholder für LLM-Aufruf – später ersetzen
        result = f"Processed input: {input_text}\nWith FAQs: {formatted_faqs}"

        # 4. Baue Antwort zurück
        return faq_pb2.FaqRewritingResponse(result=result)

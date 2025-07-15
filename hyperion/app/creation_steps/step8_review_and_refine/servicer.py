import logging
import grpc

from app.grpc import hyperion_pb2_grpc
from app.grpc.hyperion_pb2 import (
    RewriteProblemStatementResponse,
)
from app.models import get_model
from app.settings import settings
from langchain_core.prompts import PromptTemplate

from .prompts import rewrite_prompt
from .consistency_check import ConsistencyCheck

logger = logging.getLogger(__name__)
consistency_checker = ConsistencyCheck(model_name=settings.MODEL_NAME)


class ReviewAndRefineServicer(hyperion_pb2_grpc.ReviewAndRefineServicer):

    def CheckConsistency(self, request, context):
        logger.info("Running signature consistency check...")
        try:
            response = consistency_checker.check_consistency(request)
            logger.info(f"Found {len(response.issues)} consistency issues")
            return response

        except Exception as e:
            logger.error(f"Error during consistency check: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Consistency check failed: {str(e)}")
            raise

    def RewriteProblemStatement(self, request, context):
        logger.info("Rewriting problem statement text...")

        model = get_model(settings.MODEL_NAME)()

        # Set up the rewriting prompt and chain
        rewrite_prompt_template = PromptTemplate.from_template(rewrite_prompt)
        rewriter = rewrite_prompt_template | model

        # Rewrite the text
        response = rewriter.invoke({"text": request.text})
        rewritten_text = response.content.strip()

        return RewriteProblemStatementResponse(rewritten_text=rewritten_text)

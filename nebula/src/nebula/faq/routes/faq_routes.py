from fastapi import APIRouter, HTTPException
from nebula.faq.domains.data.faq_dto import FaqRewritingDTO, FaqRewritingResponse, FaqConsistencyDTO, FaqConsistencyResponse
from nebula.faq.services.rewrite_service import rewrite_faq_text
from nebula.faq.services.consistency_service import check_faq_consistency
import logging

logger = logging.getLogger("nebula.faq.routes")

router = APIRouter()

@router.post("/rewrite-faq", response_model=FaqRewritingResponse)
def rewrite_faq(request: FaqRewritingDTO):
    rewritten_text = rewrite_faq_text(
        to_be_rewritten=request.to_be_rewritten,
        faqs=request.faqs
    )

    logger.info("Response being returned: %s", FaqRewritingResponse.model_construct(
        rewrittenText=rewritten_text
    ))

    return FaqRewritingResponse(rewritten_text=rewritten_text)

@router.post("/check-consistency", response_model=FaqConsistencyResponse)
def consistency_check_faq(request: FaqConsistencyDTO):
    result = check_faq_consistency(
        faqs=request.faqs,
        to_be_checked=request.to_be_checked
    )
    logging.info("Consistency check result: %s", result)
    return result
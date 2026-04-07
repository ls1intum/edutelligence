import logging

from fastapi import APIRouter

from nebula.faq.domains.data.faq_dto import (
    FaqConsistencyDTO,
    FaqConsistencyResponse,
    FaqRewritingDTO,
    FaqRewritingResponse,
)
from nebula.faq.services.consistency_service import check_faq_consistency
from nebula.faq.services.rewrite_service import rewrite_faq_text

logger = logging.getLogger("nebula.faq.routes")

router = APIRouter()


@router.post("/rewrite-faq", response_model=FaqRewritingResponse)
def rewrite_faq(request: FaqRewritingDTO):
    rewritten_text = rewrite_faq_text(to_be_rewritten=request.to_be_rewritten)

    logger.info(
        "Response being returned: %s",
        FaqRewritingResponse.model_construct(rewritten_text=rewritten_text),
    )

    return FaqRewritingResponse(rewritten_text=rewritten_text)


@router.post("/check-consistency", response_model=FaqConsistencyResponse)
def consistency_check_faq(request: FaqConsistencyDTO):
    result = check_faq_consistency(
        faqs=request.faqs, to_be_checked=request.to_be_checked
    )
    logging.info("Consistency check result: %s", result)
    return result

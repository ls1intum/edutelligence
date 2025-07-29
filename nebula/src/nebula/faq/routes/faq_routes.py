from fastapi import APIRouter, HTTPException
from nebula.faq.domains.data.faq_dto import FaqRewritingDTO, FaqRewritingResponse
from nebula.faq.services.rewrite_service import rewrite_faq_text

router = APIRouter()

@router.post("/rewrite-faq", response_model=FaqRewritingResponse)
def rewrite_faq(request: FaqRewritingDTO):
    rewritten_text = rewrite_faq_text(
        to_be_rewritten=request.to_be_rewritten,
        faqs=request.faqs
    )

    return FaqRewritingResponse.model_construct(
        rewrittenText=rewritten_text,
        userId=request.user_id,
        courseId=request.course_id
    )
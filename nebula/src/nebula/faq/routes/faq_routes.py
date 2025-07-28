from fastapi import APIRouter, HTTPException
from nebula.faq.domains.data.faq_dto import FaqRewritingRequest
from nebula.faq.services.rewrite_service import rewrite_faq_text

router = APIRouter()

@router.post("/rewrite-faq")
def rewrite_faq(request: FaqRewritingRequest):
    rewritten_text = rewrite_faq_text(to_be_rewritten=request.to_be_rewritten, faqs=request.faqs)
    return f"rewritten request: {request.to_be_rewritten}"

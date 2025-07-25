from fastapi import APIRouter, HTTPException
from nebula.faq.domains.data.faq_dto import FaqRewritingRequest

router = APIRouter()


@router.post("/rewrite-faq")
def rewrite_faq():
    return {
        "status": "ok",
    }


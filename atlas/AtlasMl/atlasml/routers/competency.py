from fastapi import APIRouter
from fastapi.responses import JSONResponse
from atlasml.models.competency import GenerateCompetencyRequest, GenerateCompetencyResponse, Competency, CompetencyTaxonomy

router = APIRouter()

@router.post("/generate-competency", response_model=GenerateCompetencyResponse)
async def generate_competency(request: GenerateCompetencyRequest):
    return GenerateCompetencyResponse(
        competencies=[Competency(title="Competency 1", description="Description 1", taxonomy=CompetencyTaxonomy.REMEMBER)]
    )
import httpx
import logging
from typing import List, Dict, Any
from config import AgentConfig
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Try to import AtlasML internal functions for direct access when running in same server
try:
    import sys
    import os
    # Try to add AtlasML to path for internal access
    atlasml_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "AtlasMl"))
    if atlasml_path not in sys.path:
        sys.path.append(atlasml_path)
    
    from atlasml.ml.pipeline_workflows import PipelineWorkflows
    from atlasml.models.competency import Competency as AtlasCompetency
    INTERNAL_ACCESS = True
    logger.info("Atlas internal access available")
except ImportError as e:
    INTERNAL_ACCESS = False
    logger.info(f"Using external Atlas API access: {e}")


class Competency(BaseModel):
    id: str
    title: str
    description: str
    course_id: str


class SuggestCompetencyRequest(BaseModel):
    description: str
    course_id: str


class SuggestCompetencyResponse(BaseModel):
    competencies: List[Competency]


class AtlasAPIClient:
    """Client for interacting with Atlas API for competency recommendations."""
    
    def __init__(self, base_url: str = None, api_token: str = None):
        self.base_url = base_url or AgentConfig.ATLAS_API_URL or "http://localhost:8001"
        self.api_token = api_token or AgentConfig.ATLAS_API_TOKEN
        
        # Initialize internal pipeline if available
        if INTERNAL_ACCESS:
            try:
                self.pipeline = PipelineWorkflows()
                self.use_internal = True
                logger.info("Using internal AtlasML pipeline")
            except Exception as e:
                logger.warning(f"Failed to initialize internal pipeline: {e}")
                self.use_internal = False
        else:
            self.use_internal = False
        
        if not self.api_token and not self.use_internal:
            logger.warning("No Atlas API token provided - requests may fail")
        
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self.api_token:
            self.headers["Authorization"] = f"Bearer {self.api_token}"
    
    async def suggest_competencies(self, description: str, course_id: str) -> List[Competency]:
        """
        Get competency suggestions from Atlas based on description.
        
        Args:
            description: Description to find similar competencies for
            course_id: ID of the course context
            
        Returns:
            List of suggested competencies
            
        Raises:
            Exception: If API call fails
        """
        try:
            logger.info(f"Requesting competency suggestions for description: {description[:50]}...")
            
            # Use internal pipeline if available
            if self.use_internal:
                try:
                    atlas_competencies = self.pipeline.suggest_competencies_by_similarity(
                        exercise_description=description,
                        course_id=course_id,
                        top_k=5
                    )
                    
                    # Convert AtlasML Competency objects to our Competency model
                    competencies = []
                    for atlas_comp in atlas_competencies:
                        competencies.append(Competency(
                            id=atlas_comp.id,
                            title=atlas_comp.title,
                            description=atlas_comp.description,
                            course_id=atlas_comp.course_id
                        ))
                    
                    logger.info(f"Received {len(competencies)} competency suggestions via internal pipeline")
                    return competencies
                    
                except Exception as e:
                    logger.warning(f"Internal pipeline failed, falling back to API: {e}")
                    # Fall through to external API call
            
            # External API call (fallback or when internal not available)
            request_data = SuggestCompetencyRequest(
                description=description,
                course_id=course_id
            )
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/competency/suggest",
                    headers=self.headers,
                    json=request_data.model_dump()
                )
                
                if response.status_code != 200:
                    logger.error(f"Atlas API error: {response.status_code} - {response.text}")
                    raise Exception(f"Atlas API returned {response.status_code}: {response.text}")
                
                response_data = response.json()
                suggestion_response = SuggestCompetencyResponse(**response_data)
                
                logger.info(f"Received {len(suggestion_response.competencies)} competency suggestions via API")
                return suggestion_response.competencies
                
        except httpx.TimeoutException:
            logger.error("Timeout when calling Atlas API")
            raise Exception("Atlas API request timed out")
        except Exception as e:
            logger.error(f"Failed to get competency suggestions: {str(e)}")
            raise Exception(f"Failed to get competency suggestions: {str(e)}")
    
    async def health_check(self) -> bool:
        """
        Check if Atlas API is available.
        
        Returns:
            True if API is healthy, False otherwise
        """
        try:
            # If using internal pipeline, check Weaviate client
            if self.use_internal:
                try:
                    # Check if Weaviate client is alive
                    return self.pipeline.weaviate_client.is_alive()
                except Exception as e:
                    logger.error(f"Internal Atlas health check failed: {e}")
                    return False
            
            # External API health check
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers={"Accept": "application/json"}
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Atlas health check failed: {str(e)}")
            return False
    
    def format_competencies_for_display(self, competencies: List[Competency]) -> str:
        """
        Format competencies for display to the user.
        
        Args:
            competencies: List of competencies to format
            
        Returns:
            Formatted string representation
        """
        if not competencies:
            return "No competencies found."
        
        formatted = "## Suggested Competencies:\n\n"
        for i, comp in enumerate(competencies, 1):
            formatted += f"**{i}. {comp.title}**\n"
            formatted += f"   - *Description:* {comp.description}\n"
            formatted += f"   - *ID:* {comp.id}\n\n"
        
        return formatted
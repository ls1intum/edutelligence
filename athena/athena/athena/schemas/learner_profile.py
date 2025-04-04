from typing import Annotated

from pydantic import BaseModel, Field


# TODO: Go over the attributes and make sure that they match with Artemis
class LearnerProfile(BaseModel):
    """
    Model representing learner profile.

    Each preference is on a scale from 0 to 2, where:
    - 0 represents the first option (e.g., practical, creative exploration)
    - 2 represents the second option (e.g., theoretical, focused guidance)
    - 1 represents a balance between the two options
    """
    
    practical_theoretical: Annotated[int, Field(
        strict=True, 
        gt=0,
        le=2,
        description="Preference for practical (0) vs theoretical (2) feedback. 1 is balanced."
    )]
    creative_guidance: Annotated[int, Field(
        strict=True, 
        gt=0,
        le=2,
        description="Preference for creative exploration (0) vs focused guidance (2). 1 is balanced."
    )] 
    followup_summary: Annotated[int, Field(
        strict=True, 
        gt=0,
        le=2,
        description="Preference for follow-up questions (0) vs summary/conclusion (2). 1 is balanced."
    )] 
    brief_detailed: Annotated[int, Field(
        strict=True, 
        gt=0,
        le=2,
        description="Preference for brief (0) vs detailed (2) feedback. 1 is balanced."
    )]
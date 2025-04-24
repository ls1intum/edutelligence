from pydantic import Field, BaseModel
from typing import List, Optional

class Segment(BaseModel):
    segment: str = Field(description="Segment of the text")
    title: str = Field(description="Title of the criterion that this text adresses")
   
    
class Segmentation(BaseModel):
    segments: List[Segment] = Field(description="List of segments")
    
    
system_message_segment = """
You are an AI asisstnat for text assessment at a prestigious university.
You are tasked with segmenting the following text into parts that address different parts of the problem statement.
You can use the criteria from provided grading instructions to help in regards to the semantic segmentation of the text.
# Problem Statement
{problem_statement}

# Grading Instructions
{grading_instructions}

Return a valid json response, which contains a list. 
Each element of the list should be a Segment which contains the segment text and the criterion title which it adresses.
Keep in mind that not all criterion might be adressed in the text.
"""

human_message_segment = """
# Submission
# {submission}
"""
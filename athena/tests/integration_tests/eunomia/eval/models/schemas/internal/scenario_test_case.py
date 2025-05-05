from typing import List, Optional
from pydantic import BaseModel

class ScenarioTestCase(BaseModel):
    # The name should match the test case JSON file's stem
    name: str
    # Path to the JSON file containing the test case data
    file: str
    # After scenario computation, these will be filled
    expected_instructions: Optional[List[int]] = None
    expected_score: Optional[float] = None
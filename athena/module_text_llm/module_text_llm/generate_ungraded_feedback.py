# TODO XXX TODO
from typing import List, Optional, Sequence
from pydantic import BaseModel, Field
import requests
from langchain_community.llms import Ollama # type: ignore
from requests.auth import HTTPBasicAuth
import os
from athena import emit_meta#type:ignore
from athena.text import Exercise, Submission, Feedback#type:ignore
from athena.logger import logger#type:ignore
# from shared_llm.helpers.models.llama import OllamaInstance#type: ignore
from module_text_llm.config import BasicApproachConfig
from langchain_community.chat_models import ChatOllama # type: ignore

from shared_llm.helpers.llm_utils import (#type:ignore
    get_chat_prompt_with_formatting_instructions, 
    check_prompt_length_and_omit_features_if_necessary, 
    num_tokens_from_prompt,
    predict_and_parse
)
from shared_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions#type:ignore

class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

    class Config:
        title = "Feedback"


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: Sequence[FeedbackModel] = Field(description="Assessment feedbacks")

    class Config:
        title = "Assessment"

class OllamaInstance():
    auth = HTTPBasicAuth(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"])
    headers2={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    }
    ollama_endpoint = 'https://gpu-artemis.ase.cit.tum.de/ollama'
    
    
    def __init__(self):
        self.llm = Ollama( 
            model = "llama3:70b",
            base_url = self.ollama_endpoint,
            headers = self.headers2,
            )
        
    def get_llama_llama(self):
        return self.llm
    
    def invoke_this_thing(self, prompt):
        return self.llm.invoke(prompt)
    
async def generate_ungraded_feedback(exercise: Exercise, submission: Submission, config: BasicApproachConfig, debug: bool) -> List[Feedback]:
    llm = ChatOllama( 
            model = "llama3:70b",
            base_url = os.environ["OLLAMA_ENDPOINT"],
            headers ={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    },
            )
    
    available_models = llm.model
    available_models = llm.call_as_llm("for real")
    print(f"Available models: {available_models}")
    
    feedbacks = []
    # print(llm.invoke("why would this not work"))
    return feedbacks
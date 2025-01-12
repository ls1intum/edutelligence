import os
import json
from module_text_llm.in_context_learning.generate_internal import generate
from athena.text import Submission, Feedback
from typing import List

class Feedback_with_reference(Feedback):
   reference_text : str
    
def get_internal_sgi():
    file_name = 'internal_grading_instructions.json'

    # Load existing data if file exists, else create a new structure
    if os.path.exists(file_name):
        with open(file_name, 'r') as file:
            internal_instructions = json.load(file)
    else:
        internal_instructions = {}
    return internal_instructions

def write_internal_sgi(exerciseId: int, internal_instructions):
    file_name = 'internal_grading_instructions.json'
    with open(file_name, 'w') as file:
        json.dump(internal_instructions, file, indent=4)
        
def extract_text_from_reference(submission: Submission, feedbacks: List[Feedback]) -> List[Feedback_with_reference]:
    text = submission.text
    feedback_with_references = []
    for feedback in feedbacks:
        feedback_with_reference = feedback
        if feedback.index_start is not None and feedback.index_end is not None:
            feedback_with_reference.reference_text = text[feedback.index_start, feedback.index_end]
        else:
            feedback_with_reference.reference_text = "Unreferenced"
        feedback_with_references.append(feedback_with_reference)
    return feedback_with_references
    
from typing import List
from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
# from .ollama_agent.agent import MultiAgentExecutor
from module_text_llm.council_of_llamas.ollama_agent.agent import MultiAgentExecutor
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.helpers.utils import add_sentence_numbers
from module_text_llm.helpers.feedback_icl.retrieve_rag_context_icl import retrieve_rag_context_icl 

from typing import List
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range

def retrieve_previous_feedback_for_chunks(submission_segments: List[str] ,exercise_id: int) -> str:
    """
    This method takes a segment from a submission and for a given exercise id, 
    returns feedback that has been given for similar texts.
    Args:
        submission_segments: A list of segments of the submission.
        exercise_id: The id of the exercise.
    Returns:
        str: A formatted string of feedbacks which reference text similar to the submission_segment.
    """
    final_response = ""
    for segment in submission_segments:
        final_response += retrieve_rag_context_icl(segment,exercise_id)
    return final_response
# Placeholder for generate suggestions logic.
async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool, is_graded: bool):
    
    tools = [retrieve_previous_feedback_for_chunks] #icl
    agent_executor = MultiAgentExecutor(
        model = "llama3.3:latest",
        tools = tools,
        exercise = exercise,
        submission = add_sentence_numbers(submission.text),
        num_agents = 2
        )
    result = agent_executor.invoke_deliberation(rounds = 5, consensus_mechanism = "unanimity")

    grading_instruction_ids = set(
        grading_instruction.id 
        for criterion in exercise.grading_criteria or [] 
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks = []
    for feedback in result["feedbacks"]:
        index_start, index_end = get_index_range_from_line_range(feedback.get("line_start"), feedback.get("line_end"), submission.text)
        grading_instruction_id = feedback.get("grading_instruction_id") if feedback.get("grading_instruction_id") in grading_instruction_ids else None
        feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback["title"],
            description=feedback["description"],
            index_start=index_start,
            index_end=index_end,
            credits=feedback["credits"],
            is_graded=is_graded,
            structured_grading_instruction_id=grading_instruction_id,
            meta={}
        ))

    return feedbacks
    
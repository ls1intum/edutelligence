from typing import List
from module_text_llm.approach_config import ApproachConfig
from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import (
    get_chat_prompt_with_formatting_instructions, 
    check_prompt_length_and_omit_features_if_necessary, 
    num_tokens_from_prompt,
)
from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions
from module_text_llm.icl_rag_approach.prompt_generate_suggestions import AssessmentModel
from module_text_llm.index_storage import retrieve_embedding_index, retrieve_feedbacks
from module_text_llm.storage_embeddings import query_embedding
from module_text_llm.generate_embeddings import embed_text
from athena.text import get_stored_feedback

def format_rag_context(rag_context):
    formatted_string = ""
    
    for context_item in rag_context:
        submission_text = context_item["submission"]
        feedback_list = context_item["feedback"]
        
        # Format submission text
        # formatted_string += f"**Submission:**\n{submission_text}\n\n"
        
        # Format feedback list
        formatted_string += f"**Tutor provided Feedback from previous submissions of this same exercise:**\n"
        for idx, feedback in enumerate(feedback_list, start=1):
            if (feedback["index_start"] is not None) and (feedback["index_end"] is not None):
                feedback["text_reference"] = submission_text[feedback["index_start"]:feedback["index_end"]]
            clean_feedback = {key: value for key, value in feedback.items() if key not in ["id","index_start","index_end","is_graded","meta"]} 

            formatted_string += f"{idx}. {clean_feedback}\n"

            # formatted_string += f"{idx}. {feedback}\n"
            # if (feedback["index_start"] is not None) and (feedback["index_end"] is not None):
            #     formatted_string += f"Referenced Text: {submission_text[feedback['index_start']:feedback['index_end']]}\n"
        # Add a separator between submissions
        formatted_string += "\n" + "-"*40 + "\n"
    
    return formatted_string
async def generate_suggestions(exercise: Exercise, submission: Submission, config:ApproachConfig, debug: bool, is_graded :bool) -> List[Feedback]:
    model = config.model.get_model()  # type: ignore[attr-defined]
    query_submission= embed_text(submission.text)
    
    rag_context = []
    
    list_of_indices = query_embedding(query_submission)
    if list_of_indices is not None:
        logger.info("List of indices: %s", list_of_indices)
        for index in list_of_indices[0]:
            if index != -1:
                exercise_id, submission_id = retrieve_embedding_index(list_of_indices)
                stored_feedback = retrieve_feedbacks(index) # -> List[Feedback]
                # stored_feedback = list(get_stored_feedback(exercise_id, submission_id))
                logger.info("Stored feedback:")
                if stored_feedback is not None:
                    for feedback_item in stored_feedback:
                        logger.info("- %s", feedback_item) 

                logger.info("Stored submission:")
                rag_context.append({"submission": submission.text, "feedback": stored_feedback})
        
        formatted_rag_context = format_rag_context(rag_context)
    else:
        formatted_rag_context = "There are no submission at the moment"
        
    logger.info("Formatted RAG context %s:", formatted_rag_context)
    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "rag_context": formatted_rag_context,
        "submission": add_sentence_numbers(submission.text)
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.generate_suggestions_prompt.system_message, 
        human_message=config.generate_suggestions_prompt.human_message, 
        pydantic_object=AssessmentModel
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = ["example_solution", "problem_statement", "grading_instructions"]
    prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=chat_prompt,
        prompt_input= prompt_input,
        max_input_tokens=config.max_input_tokens+7000,
        omittable_features=omittable_features,
        debug=debug
    )

    # Skip if the prompt is too long
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", chat_prompt.format(**prompt_input))
            emit_meta("error", f"Input too long {num_tokens_from_prompt(chat_prompt, prompt_input)} > {config.max_input_tokens}")
        return []

    result = await predict_and_parse(
        model=model, 
        chat_prompt=chat_prompt, 
        prompt_input=prompt_input, 
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.id}",
            f"submission-{submission.id}",
        ],
        use_function_calling=True
    )

    if debug:
        emit_meta("generate_suggestions", {
            "prompt": chat_prompt.format(**prompt_input),
            "result": result.dict() if result is not None else None
        })

    if result is None:
        return []

    grading_instruction_ids = set(
        grading_instruction.id 
        for criterion in exercise.grading_criteria or [] 
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks = []
    for feedback in result.feedbacks:
        index_start, index_end = get_index_range_from_line_range(feedback.line_start, feedback.line_end, submission.text)
        grading_instruction_id = feedback.grading_instruction_id if feedback.grading_instruction_id in grading_instruction_ids else None
        feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            index_start=index_start,
            index_end=index_end,
            credits=feedback.credits,
            is_graded=is_graded,
            structured_grading_instruction_id=grading_instruction_id,
            meta={}
        ))

    return feedbacks
